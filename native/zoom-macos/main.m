// Zoom receiver. Probe mode logs frame diagnostics only; voice mode additionally
// runs the loopback PCM bridge shared with the Linux path. No PCM, meeting
// credentials, or JWTs are logged.
#import <Cocoa/Cocoa.h>
#import <ZoomSDK/ZoomSDK.h>
#import <ZoomSDK/ZoomSDKRawDataAudioSourceController.h>
#include <arpa/inet.h>
#include <libkern/OSByteOrder.h>
#include <errno.h>
#include <pthread.h>
#include <signal.h>
#include <stdint.h>
#include <sys/socket.h>
#include <time.h>
#include <unistd.h>

// Loopback TCP bridge. Same wire protocol as native/zoom-linux/VoiceBridge.cpp:
// type:1 byte + length:4 bytes big-endian + payload. Network I/O never runs
// inside the Zoom audio callback.
static _Atomic int bridge_client = -1;
static _Atomic BOOL bridge_sending = NO, bridge_playing = NO;
static _Atomic unsigned bridge_generation = 0;
static _Atomic long long bridge_gate_until = 0;
static BOOL bridge_mixed_audio = NO;
static char bridge_token[65];
static int bridge_port;
static BOOL bridge_participant_audio = YES;
static _Atomic unsigned bridge_self_id = 0;
static long long bridge_audio_origin;
static long long bridge_sdk_origin = -1, bridge_sdk_offset;
static pthread_mutex_t clock_mutex = PTHREAD_MUTEX_INITIALIZER;
static _Atomic long long bridge_last_heartbeat = 0;
static ZoomSDKAudioRawDataSender *bridge_sender;  // sender_mutex
static NSMutableArray<NSData *> *bridge_outgoing; // out_mutex
static NSData *bridge_pending;                    // play_mutex; first 4 bytes are the playback id
static NSData *bridge_cancel_id;                  // play_mutex; acknowledgement after worker quiesces
static pthread_mutex_t out_mutex = PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t out_cv = PTHREAD_COND_INITIALIZER;
static pthread_mutex_t play_mutex = PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t play_cv = PTHREAD_COND_INITIALIZER;
static pthread_mutex_t sender_mutex = PTHREAD_MUTEX_INITIALIZER;

static long long bridge_millis(void) {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return ts.tv_sec * 1000LL + ts.tv_nsec / 1000000;
}
static void bridge_fail(void) {
    int fd = bridge_client;
    if (fd >= 0) shutdown(fd, SHUT_RDWR);
    bridge_generation++;
}
static void bridge_emit(char type, const void *data, unsigned size) {
    if (bridge_client < 0) return;
    NSMutableData *packet = [[NSMutableData alloc] initWithLength:5 + size];
    char *bytes = packet.mutableBytes;
    bytes[0] = type;
    uint32_t length = htonl(size);
    memcpy(bytes + 1, &length, 4);
    if (size) memcpy(bytes + 5, data, size);
    pthread_mutex_lock(&out_mutex);
    if (bridge_outgoing.count >= 500) {
        pthread_mutex_unlock(&out_mutex);
        bridge_fail();
        return;
    }
    [bridge_outgoing addObject:packet];
    pthread_mutex_unlock(&out_mutex);
    pthread_cond_signal(&out_cv);
}
// Fixed classifications and numeric values only, never SDK strings or PCM.
static void bridge_error_detail(const char *reason, int result, unsigned playback_id, unsigned frame_index) {
    NSDictionary *detail = @{@"version": @1, @"reason": @(reason), @"sdk_result": @(result),
                              @"playback_id": @(playback_id), @"frame_index": @(frame_index)};
    NSData *payload = [NSJSONSerialization dataWithJSONObject:detail options:0 error:nil];
    printf("BRIDGE_ERROR %.*s\n", (int)payload.length, (const char *)payload.bytes);
    bridge_emit('E', payload.bytes, (unsigned)payload.length);
}
static void bridge_error(const char *reason) { bridge_error_detail(reason, -1, 0, 0); }
static void bridge_cancel(NSData *identifier) {
    pthread_mutex_lock(&play_mutex);
    bridge_generation++;
    bridge_pending = nil;
    if (bridge_playing) bridge_cancel_id = identifier;
    else bridge_emit('K', identifier.bytes, 4);
    pthread_mutex_unlock(&play_mutex);
}
static BOOL bridge_transfer(int fd, void *data, size_t size, BOOL writing) {
    char *cursor = data;
    while (size) {
        ssize_t n = writing ? send(fd, cursor, size, 0) : recv(fd, cursor, size, 0);
        if (n < 0 && errno == EINTR) continue;
        if (n <= 0) return NO;
        cursor += n;
        size -= n;
    }
    return YES;
}
// Sends pending PCM to the virtual microphone paced at 20 ms per 1280-byte chunk.
static void *bridge_playback(void *unused) {
    for (;;) {
        NSData *data;
        unsigned gen;
        pthread_mutex_lock(&play_mutex);
        while (!bridge_pending) pthread_cond_wait(&play_cv, &play_mutex);
        data = bridge_pending;
        bridge_pending = nil;
        bridge_playing = YES; // Reserve the slot while holding play_mutex.
        gen = bridge_generation;
        pthread_mutex_unlock(&play_mutex);
        BOOL ok = YES;
        int sdk_result = -1;
        const char *failure_reason = "microphone_unavailable";
        long long next = bridge_millis(), began = next, previous = next;
        double max_gap = 0, min_gap = 1000000, early_max_gap = 0, max_send = 0;
        unsigned frames = 0, short_gaps = 0, long_gaps = 0;
        const char *bytes = data.bytes;
        for (NSUInteger offset = 4; offset < data.length; offset += 1280) {
            if (gen != bridge_generation) { ok = NO; break; }
            char chunk[1280] = {0};
            memcpy(chunk, bytes + offset, MIN((NSUInteger)1280, data.length - offset));
            ZoomSDKError result;
            pthread_mutex_lock(&sender_mutex);
            if (!bridge_sender || !bridge_sending) {
                pthread_mutex_unlock(&sender_mutex);
                ok = NO;
                break;
            }
            long long now = bridge_millis();
            double gap = (double)(now - previous);
            if (frames) {
                max_gap = MAX(max_gap, gap); min_gap = MIN(min_gap, gap);
                if (now - began < 2000) early_max_gap = MAX(early_max_gap, gap);
                if (gap < 5) ++short_gaps;
                if (gap > 40) ++long_gaps;
            }
            previous = now; ++frames;
            result = [bridge_sender send:chunk dataLength:1280 sampleRate:32000 channel:ZoomSDKAudioChannel_Mono];
            max_send = MAX(max_send, (double)(bridge_millis() - now));
            pthread_mutex_unlock(&sender_mutex);
            if (result != ZoomSDKError_Success) {
                sdk_result = (int)result; failure_reason = "sdk_send_failed"; ok = NO; break;
            }
            if (offset == 4) bridge_emit('S', bytes, 4);
            next += 20;
            // A missed deadline must not trigger a burst of stale PCM frames.
            long long completed = bridge_millis();
            if (next <= completed) next = completed + 20;
            long long delay = next - bridge_millis();
            if (delay > 0) usleep((useconds_t)delay * 1000);
        }
        uint32_t playback_id;
        memcpy(&playback_id, bytes, 4);
        printf("BRIDGE_PLAYBACK id=%u frames=%u max_gap_ms=%.1f min_gap_ms=%.1f early_max_gap_ms=%.1f gaps_under_5ms=%u gaps_over_40ms=%u max_send_ms=%.1f\n",
               ntohl(playback_id), frames, max_gap, min_gap, early_max_gap, short_gaps, long_gaps, max_send);
        bridge_gate_until = bridge_millis() + 350;
        pthread_mutex_lock(&play_mutex);
        bridge_playing = NO;
        if (ok && gen == bridge_generation) bridge_emit('D', bytes, 4);
        else if (!ok && gen == bridge_generation)
            bridge_error_detail(failure_reason, sdk_result, ntohl(playback_id), frames);
        if (bridge_cancel_id) {
            bridge_emit('K', bridge_cancel_id.bytes, 4);
            bridge_cancel_id = nil;
        }
        pthread_mutex_unlock(&play_mutex);
    }
    return NULL;
}
static void *bridge_writer(void *arg) {
    int fd = (int)(intptr_t)arg;
    for (;;) {
        NSData *packet;
        pthread_mutex_lock(&out_mutex);
        while (!bridge_outgoing.count && bridge_client >= 0)
            pthread_cond_wait(&out_cv, &out_mutex);
        if (bridge_client < 0) {
            pthread_mutex_unlock(&out_mutex);
            return NULL;
        }
        packet = bridge_outgoing[0];
        [bridge_outgoing removeObjectAtIndex:0];
        pthread_mutex_unlock(&out_mutex);
        if (!bridge_transfer(fd, (void *)packet.bytes, packet.length, YES)) {
            bridge_fail();
            return NULL;
        }
    }
}
static void *bridge_serve(void *unused) {
    int server = socket(AF_INET, SOCK_STREAM, 0), one = 1;
    setsockopt(server, SOL_SOCKET, SO_REUSEADDR, &one, sizeof(one));
    struct sockaddr_in addr = {0};
    addr.sin_family = AF_INET;
    addr.sin_port = htons(bridge_port);
    addr.sin_addr.s_addr = htonl(INADDR_LOOPBACK);  // Loopback only; no container boundary on macOS.
    if (bind(server, (struct sockaddr *)&addr, sizeof(addr)) || listen(server, 1)) {
        printf("BRIDGE_LISTEN_FAILED\n");
        return NULL;
    }
    printf("BRIDGE_LISTENING\n");
    for (;;) {
        int fd = accept(server, NULL, NULL);
        if (fd < 0) continue;
        // A closed Python peer must fail I/O, not kill the SDK process with SIGPIPE.
        setsockopt(fd, SOL_SOCKET, SO_NOSIGPIPE, &one, sizeof(one));
        struct timeval timeout = {5, 0};
        setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, &timeout, sizeof(timeout));
        setsockopt(fd, SOL_SOCKET, SO_SNDTIMEO, &timeout, sizeof(timeout));
        char auth[64];
        if (!bridge_transfer(fd, auth, 64, NO) || memcmp(auth, bridge_token, 64)) {
            close(fd);
            continue;
        }
        timeout = (struct timeval){0, 0};
        setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, &timeout, sizeof(timeout));
        pthread_mutex_lock(&out_mutex);
        [bridge_outgoing removeAllObjects];
        pthread_mutex_unlock(&out_mutex);
        bridge_client = fd;
        bridge_emit('H', "cancel-v1,dual-input-v1", (unsigned)strlen("cancel-v1,dual-input-v1"));
        if (bridge_sending) bridge_emit('M', NULL, 0);
        pthread_t writer;
        pthread_create(&writer, NULL, bridge_writer, (void *)(intptr_t)fd);
        char header[5];
        while (bridge_transfer(fd, header, 5, NO)) {
            uint32_t size;
            memcpy(&size, header + 1, 4);
            size = ntohl(size);
            if (size > 1920004) break;
            NSMutableData *payload = [[NSMutableData alloc] initWithLength:size];
            if (size && !bridge_transfer(fd, payload.mutableBytes, size, NO)) break;
            if (header[0] == 'C' && size == 4) {
                bridge_cancel(payload);
            } else if (header[0] == 'P' && size > 4 && size % 2 == 0) {
                pthread_mutex_lock(&play_mutex);
                if (bridge_playing || bridge_pending) bridge_error("playback_active");
                else if (!bridge_sending) bridge_error("microphone_unavailable");
                else {
                    bridge_pending = payload;
                    pthread_cond_signal(&play_cv);
                }
                pthread_mutex_unlock(&play_mutex);
            } else break;
        }
        bridge_fail();
        bridge_client = -1;
        pthread_cond_broadcast(&out_cv);
        pthread_join(writer, NULL);
        close(fd);
        pthread_mutex_lock(&play_mutex);
        bridge_pending = nil;
        bridge_cancel_id = nil;
        pthread_mutex_unlock(&play_mutex);
    }
    return NULL;
}
static void bridge_start(NSDictionary *config) {
    strlcpy(bridge_token, [config[@"bridge_token"] UTF8String], sizeof(bridge_token));
    bridge_port = [config[@"bridge_port"] intValue];
    bridge_outgoing = [NSMutableArray new];
    pthread_t thread;
    pthread_create(&thread, NULL, bridge_playback, NULL);
    pthread_detach(thread);
    pthread_create(&thread, NULL, bridge_serve, NULL);
    pthread_detach(thread);
}
static void bridge_set_sender(ZoomSDKAudioRawDataSender *sender) {
    pthread_mutex_lock(&sender_mutex);
    bridge_sender = sender;
    pthread_mutex_unlock(&sender_mutex);
}
static void bridge_set_sending(BOOL value) {
    bridge_sending = value;
    if (value) bridge_emit('M', NULL, 0);
    else {
        bridge_generation++;
        bridge_emit('N', NULL, 0);
    }
}
// Prefer the SDK media clock so delayed/batched callbacks do not compress time.
// The SDK returns zero when a timestamp is unavailable; only then estimate from callback time.
static long long bridge_timestamp(ZoomSDKAudioRawData *data) {
    long long raw = [data getTimeStamp];
    long long estimated = MAX(0LL, bridge_millis() - bridge_audio_origin - [data getBufferLen] / 64);
    if (raw <= 0) return estimated;
    pthread_mutex_lock(&clock_mutex);
    if (bridge_sdk_origin < 0) { bridge_sdk_origin = raw; bridge_sdk_offset = estimated; }
    long long result = MAX(0LL, bridge_sdk_offset + raw - bridge_sdk_origin);
    pthread_mutex_unlock(&clock_mutex);
    return result;
}
// Per-user packet: user ID (u32 BE), meeting-relative frame start (u64 BE), PCM.
static void bridge_user_audio(ZoomSDKAudioRawData *data, unsigned userID) {
    if (bridge_client < 0 || !bridge_self_id || userID == bridge_self_id) return;
    const char *buffer = [data getBuffer];
    unsigned int rate = [data getSampleRate], channels = [data getChannelNum], size = [data getBufferLen];
    if (!buffer || !size || channels != 1 || rate != 32000 || size % 2 || size > 63988) {
        bridge_error("invalid_input_format");
        return;
    }
    NSMutableData *packet = [[NSMutableData alloc] initWithLength:12 + size];
    char *bytes = packet.mutableBytes;
    uint32_t user = htonl(userID);
    uint64_t timestamp = OSSwapHostToBigInt64(bridge_timestamp(data));
    memcpy(bytes, &user, 4);
    memcpy(bytes + 4, &timestamp, 8);
    memcpy(bytes + 12, buffer, size);
    // Other participants remain audible during bot playback. Never send mixed PCM.
    bridge_emit('U', bytes, (unsigned)packet.length);
}

@interface SparkieReceiver : NSObject <NSApplicationDelegate, ZoomSDKAuthDelegate,
    ZoomSDKMeetingServiceDelegate, ZoomSDKMeetingRecordDelegate, ZoomSDKAudioRawDataDelegate,
    ZoomSDKVirtualAudioMicDelegate>
@property NSDictionary *config;
@property ZoomSDKAudioRawDataHelper *audio;
@property BOOL voice;
@property BOOL recording;
@property BOOL requested;
@property BOOL stopping;
@property BOOL hostMuted;
@property int exitCode;
@property unsigned long long frames;
@property unsigned long long bytes;
@property int peak;
@property NSTimer *participantTimer;
@property NSTimer *unmuteTimer;
@property NSData *lastParticipants;
- (void)publishParticipants;
- (void)ensureUnmuted;
- (void)shutdown;
@end

@implementation SparkieReceiver
- (void)applicationDidFinishLaunching:(NSNotification *)notification {
    BOOL checkOnly = [NSProcessInfo.processInfo.arguments containsObject:@"--check"];
    if (!checkOnly) {
        NSString *configPath = NSProcessInfo.processInfo.environment[@"SPARKIE_ZOOM_CONFIG"];
        NSData *data = configPath ? [NSData dataWithContentsOfFile:configPath] : nil;
        self.config = data ? [NSJSONSerialization JSONObjectWithData:data options:0 error:nil] : nil;
        if (![self.config isKindOfClass:NSDictionary.class]) {
            printf("CONFIG_MISSING_OR_INVALID\n"); exit(1);
        }
        for (NSString *key in @[@"token", @"meeting_number", @"meeting_password", @"display_name"]) {
            if (![self.config[key] isKindOfClass:NSString.class] || ![self.config[key] length]) {
                printf("CONFIG_INVALID\n"); exit(1);
            }
        }
        self.voice = [self.config[@"voice"] boolValue];
        bridge_participant_audio = self.config[@"participant_audio"] ? [self.config[@"participant_audio"] boolValue] : YES;
        bridge_mixed_audio = [self.config[@"mixed_audio"] boolValue] || !bridge_participant_audio;
        if (self.voice) {
            id port = self.config[@"bridge_port"];
            NSString *token = self.config[@"bridge_token"];
            if (![port respondsToSelector:@selector(intValue)] || [port intValue] <= 0 || [port intValue] > 65535 ||
                ![token isKindOfClass:NSString.class] || token.length != 64) {
                printf("CONFIG_INVALID\n"); exit(1);
            }
            bridge_start(self.config);
        }
    }
    ZoomSDKInitParams *params = [ZoomSDKInitParams new];
    params.zoomDomain = @"https://zoom.us";
    params.needCustomizedUI = NO;
    params.enableLog = NO;
    printf("SDK_INIT_BEGIN (check macOS Keychain prompts if this stalls)\n");
    ZoomSDKError result = [[ZoomSDK sharedSDK] initSDKWithParams:params];
    printf("SDK_INIT result=%d\n", result);
    if (result != ZoomSDKError_Success) { self.exitCode = 1; [self shutdown]; return; }
    if (checkOnly) {
        printf("SDK_LOAD_CHECK_OK (no authentication or meeting join attempted)\n");
        [self shutdown]; return;
    }
    ZoomSDKAuthService *auth = [[ZoomSDK sharedSDK] getAuthService];
    auth.delegate = self;
    ZoomSDKAuthContext *context = [ZoomSDKAuthContext new];
    context.jwtToken = self.config[@"token"];
    result = [auth sdkAuth:context];
    printf("SDK_AUTH_REQUEST result=%d\n", result);
    if (result != ZoomSDKError_Success) { self.exitCode = 1; [self shutdown]; }
    // A synchronous success only means accepted. Detect missing auth callbacks.
    dispatch_after(dispatch_time(DISPATCH_TIME_NOW, 60 * NSEC_PER_SEC), dispatch_get_main_queue(), ^{
        if (!self.stopping && self.config[@"token"]) {
            printf("SDK_AUTH_TIMEOUT\n"); self.exitCode = 1; [self shutdown];
        }
    });
}
- (void)onZoomSDKAuthReturn:(ZoomSDKAuthError)result {
    printf("SDK_AUTH_RESULT result=%d\n", result);
    if (result != ZoomSDKAuthError_Success) { self.exitCode = 1; [self shutdown]; return; }
    NSMutableDictionary *config = [self.config mutableCopy];
    [config removeObjectForKey:@"token"];
    self.config = config;
    ZoomSDKAudioSetting *settings = [[[ZoomSDK sharedSDK] getSettingService] getAudioSetting];
    // Join muted so installing the external source precedes the unmute transition.
    // Joining already unmuted can initialize the source without onMicStartSend.
    ZoomSDKError mute = [settings enableMuteMicJoinVoip:YES];
    printf("MUTE_ON_JOIN result=%d\n", mute);
    if (!settings || mute != ZoomSDKError_Success) { self.exitCode = 1; [self shutdown]; return; }
    [settings enableAutoJoinVoip:YES];
    ZoomSDKMeetingService *meeting = [[ZoomSDK sharedSDK] getMeetingService];
    meeting.delegate = self;
    meeting.getRecordController.delegate = self;
    ZoomSDKJoinMeetingElements *join = [ZoomSDKJoinMeetingElements new];
    join.userType = ZoomSDKUserType_WithoutLogin;
    join.meetingNumber = [self.config[@"meeting_number"] longLongValue];
    join.password = self.config[@"meeting_password"];
    join.displayName = self.config[@"display_name"];
    join.isNoVideo = YES;
    join.isNoAudio = NO;
    ZoomSDKError joined = [meeting joinMeeting:join];
    printf("JOIN_REQUEST result=%d\n", joined);
    self.config = @{};
    if (joined != ZoomSDKError_Success) { self.exitCode = 1; [self shutdown]; }
}
- (void)onZoomAuthIdentityExpired {
    printf("SDK_AUTH_EXPIRED restart_required=1\n"); self.exitCode = 1; [self shutdown];
}
- (void)onMeetingStatusChange:(ZoomSDKMeetingStatus)state meetingError:(ZoomSDKMeetingError)error EndReason:(EndMeetingReason)reason {
    printf("MEETING_STATUS state=%d error=%d reason=%d\n", state, error, reason);
    if (self.stopping) return;
    if (state == ZoomSDKMeetingStatus_InMeeting) {
        printf("In Meeting Now...\n");
        ZoomSDKMeetingActionController *actions = [[[ZoomSDK sharedSDK] getMeetingService] getMeetingActionController];
        if (self.voice) {
            // Install the virtual microphone before unmuting; the physical mic is never opened.
            ZoomSDKRawDataAudioSourceController *source = nil;
            ZoomSDKError helper = [[[ZoomSDK sharedSDK] getRawDataController] getRawDataAudioSourceHelper:&source];
            if (helper == ZoomSDKError_Success && source) {
                ZoomSDKError installed = [source setExternalAudioSource:self];
                printf("AUDIO_SOURCE_SET result=%d\n", installed);
                if (installed != ZoomSDKError_Success) {
                    self.exitCode = 1; [self shutdown]; return;
                }
            } else {
                printf("AUDIO_SOURCE_HELPER result=%d\n", helper);
                self.exitCode = 1; [self shutdown]; return;
            }
        }
        printf("JOIN_VOIP result=%d\n", [actions actionMeetingWithCmd:ActionMeetingCmd_JoinVoip userID:0 onScreen:0]);
        if (self.voice) {
            printf("UNMUTE_REQUEST result=%d\n", [actions actionMeetingWithCmd:ActionMeetingCmd_UnMuteAudio userID:0 onScreen:0]);
            // The SDK accepts unmute before VoIP audio is fully connected and may
            // silently drop it; retry until onMicStartSend reports real unmute.
            self.unmuteTimer = [NSTimer scheduledTimerWithTimeInterval:2 target:self
                selector:@selector(ensureUnmuted) userInfo:nil repeats:YES];
        }
        bridge_self_id = [[actions getMyself] getUserID];
        if (self.voice && !self.participantTimer) {
            self.participantTimer = [NSTimer scheduledTimerWithTimeInterval:1 target:self
                selector:@selector(publishParticipants) userInfo:nil repeats:YES];
        }
        [self publishParticipants];
        [self tryAudio];
    } else if (state == ZoomSDKMeetingStatus_Failed) {
        self.exitCode = 1; [self shutdown];
    } else if (state == ZoomSDKMeetingStatus_Ended) {
        [self shutdown];
    }
}
- (void)publishParticipants {
    if (!self.voice || bridge_client < 0) return;
    ZoomSDKMeetingActionController *actions = [[[ZoomSDK sharedSDK] getMeetingService] getMeetingActionController];
    bridge_self_id = [[actions getMyself] getUserID];
    NSMutableArray *users = [NSMutableArray new];
    for (NSNumber *ident in [actions getParticipantsList]) {
        ZoomSDKUserInfo *user = [actions getUserByUserID:ident.unsignedIntValue];
        if (!user) continue;
        NSString *name = [user getUserName] ?: @"";
        if (name.length > 256) name = [name substringToIndex:256];
        [users addObject:@{@"user_id": ident, @"name": name, @"is_self": @([user isMySelf])}];
    }
    NSData *data = [NSJSONSerialization dataWithJSONObject:users options:NSJSONWritingSortedKeys error:nil];
    if (data.length > 64000) { bridge_error("Participant metadata exceeds bridge limit"); return; }
    if (data && ![data isEqualToData:self.lastParticipants]) {
        bridge_emit('J', data.bytes, (unsigned)data.length);
        self.lastParticipants = data;
    }
}
- (void)tryAudio {
    if (self.recording || self.stopping) return;
    ZoomSDKMeetingRecordController *record = [[[ZoomSDK sharedSDK] getMeetingService] getRecordController];
    if ([record canStartRawRecording] != ZoomSDKError_Success) {
        if (!self.requested) {
            self.requested = YES;
            printf("REQUEST_RECORDING_PRIVILEGE result=%d\n", [record requestLocalRecordingPrivilege]);
        }
        return;
    }
    ZoomSDKError result = [record startRawRecording];
    printf("START_RAW_RECORDING result=%d\n", result);
    if (result != ZoomSDKError_Success) return;
    self.recording = YES;
    ZoomSDKAudioRawDataHelper *helper = nil;
    result = [[[ZoomSDK sharedSDK] getRawDataController] getAudioRawDataHelper:&helper];
    if (result == ZoomSDKError_Success && helper) {
        self.audio = helper;
        helper.delegate = self;
        bridge_audio_origin = bridge_millis();
        result = [helper subscribe];
        printf("AUDIO_SUBSCRIBE result=%d\n", result);
    } else {
        printf("AUDIO_HELPER result=%d\n", result);
    }
    if (result != ZoomSDKError_Success || !helper) {
        self.exitCode = 1; [self shutdown];
    }
}
- (void)onRecordPrivilegeChange:(BOOL)canRecord {
    dispatch_async(dispatch_get_main_queue(), ^{
        printf("RECORDING_PRIVILEGE allowed=%d\n", canRecord);
        if (canRecord) [self tryAudio];
        else if (self.recording) {
            [self.audio unSubscribe]; self.audio.delegate = nil; self.audio = nil;
            [[[[ZoomSDK sharedSDK] getMeetingService] getRecordController] stopRawRecording];
            self.recording = NO;
        }
    });
}
- (void)onLocalRecordingPrivilegeRequestStatus:(ZoomSDKRequestLocalRecordingStatus)status {
    printf("RECORDING_REQUEST_STATUS status=%d\n", status);
}
// Required protocol callbacks for features this probe does not enable.
- (void)onRecord2MP4Done:(BOOL)success Path:(NSString *)recordPath {}
- (void)onRecord2MP4Progressing:(int)percentage {}
- (void)onCloudRecordingStatus:(ZoomSDKRecordingStatus)status {}
- (void)onCustomizedRecordingSourceReceived:(CustomizedRecordingLayoutHelper *)helper {}
- (void)onLocalRecordStatus:(ZoomSDKRecordingStatus)status userID:(unsigned int)userID {}
- (void)onLocalRecordingPrivilegeRequested:(ZoomSDKRequestLocalRecordingPrivilegeHandler *)handler {}
- (void)onCloudRecordingStorageFull:(time_t)gracePeriodDate {}
- (void)onRequestCloudRecordingResponse:(ZoomSDKRequestStartCloudRecordingStatus)status {}
- (void)onStartCloudRecordingRequested:(ZoomSDKRequestStartCloudRecordingHandler *)handler {}
- (void)onEnableAndStartSmartRecordingRequested:(ZoomSDKRequestEnableAndStartSmartRecordingHandler *)handler {}
- (void)onSmartRecordingEnableActionCallback:(ZoomSDKSmartRecordingEnableActionHandler *)handler {}
// Re-arm the virtual microphone when the SDK resets our audio to self-muted
// (e.g. mute-on-join applied when VoIP finishes connecting). Host-forced mutes
// (MutedByHost / MutedAllByHost) are respected, not fought.
- (void)ensureUnmuted {
    if (!self.voice || self.stopping || bridge_sending) {
        [self.unmuteTimer invalidate]; self.unmuteTimer = nil;
        return;
    }
    if (self.hostMuted) return;
    ZoomSDKMeetingActionController *actions = [[[ZoomSDK sharedSDK] getMeetingService] getMeetingActionController];
    printf("UNMUTE_RETRY\n");
    [actions actionMeetingWithCmd:ActionMeetingCmd_UnMuteAudio userID:0 onScreen:0];
}
- (void)onUserAudioStatusChange:(NSArray *)statuses {
    if (!self.voice || self.stopping) return;
    ZoomSDKMeetingActionController *actions = [[[ZoomSDK sharedSDK] getMeetingService] getMeetingActionController];
    unsigned int mine = [[actions getMyself] getUserID];
    for (ZoomSDKUserAudioStatus *entry in statuses) {
        if (![entry isKindOfClass:ZoomSDKUserAudioStatus.class] || [entry getUserID] != mine) continue;
        ZoomSDKAudioStatus status = [entry getStatus];
        printf("AUDIO_STATUS status=%d\n", status);
        self.hostMuted = (status == ZoomSDKAudioStatus_MutedByHost ||
                          status == ZoomSDKAudioStatus_MutedAllByHost);
        if (status == ZoomSDKAudioStatus_Muted) {
            printf("AUDIO_STATUS self_muted rearm=1\n");
            [actions actionMeetingWithCmd:ActionMeetingCmd_UnMuteAudio userID:0 onScreen:0];
        }
    }
}
// Virtual microphone callbacks; only active in voice mode.
- (void)onMicInitialize:(ZoomSDKAudioRawDataSender *)rawdataSender {
    printf("ZOOM_MIC_INITIALIZED\n");
    bridge_set_sender(rawdataSender);
}
- (void)onMicStartSend {
    printf("ZOOM_MIC_READY\n");
    bridge_set_sending(YES);
}
- (void)onMicStopSend { printf("ZOOM_MIC_STOP_SEND\n"); bridge_set_sending(NO); }
- (void)onMicUninitialized {
    printf("ZOOM_MIC_UNINITIALIZED\n");
    bridge_set_sending(NO);
    bridge_set_sender(nil);
}
- (void)onMixedAudioRawDataReceived:(ZoomSDKAudioRawData *)data {
    const char *buffer = [data getBuffer];
    unsigned int size = [data getBufferLen];
    if (!buffer || !size) return;
    if (self.voice && bridge_participant_audio) {
        // Mixed callbacks only establish the clock and report health in per-user mode.
        (void)bridge_timestamp(data);
        if (bridge_millis() - bridge_last_heartbeat >= 1000) {
            bridge_last_heartbeat = bridge_millis();
            bridge_emit('R', NULL, 0);
        }
    }
    if (self.voice && bridge_mixed_audio && bridge_client >= 0) {
        if ([data getChannelNum] != 1 || [data getSampleRate] != 32000 || size % 2 || size > 64000) {
            bridge_error("invalid_input_format");
            return;
        }
        NSMutableData *pcm = [[NSMutableData alloc] initWithLength:size];
        if (!bridge_playing && bridge_millis() >= bridge_gate_until) memcpy(pcm.mutableBytes, buffer, size);
        bridge_emit('A', pcm.bytes, size);
    }
    @synchronized (self) {
        self.frames++; self.bytes += size;
        for (unsigned int i = 0; i + 1 < size; i += 2) {
            int16_t sample; memcpy(&sample, buffer + i, sizeof(sample));
            self.peak = MAX(self.peak, abs((int)sample));
        }
        if (self.frames == 1 || self.frames % 100 == 0) {
            printf("ZOOM_AUDIO_FRAME_RECEIVED frames=%llu bytes=%llu sample_rate=%u channels=%u\n", self.frames, self.bytes, [data getSampleRate], [data getChannelNum]);
            printf("ZOOM_AUDIO_LEVEL peak=%d\n", self.peak);
            self.peak = 0;
        }
    }
}
// Required deprecated method remains empty to avoid double ingestion; target SDK 7.1.5 uses userID.
- (void)onOneWayAudioRawDataReceived:(ZoomSDKAudioRawData *)data nodeID:(unsigned int)nodeID {}
- (void)onOneWayAudioRawDataReceived:(ZoomSDKAudioRawData *)data userID:(unsigned int)userID {
    if (self.voice && bridge_participant_audio) bridge_user_audio(data, userID);
}
- (void)onShareAudioRawDataReceived:(ZoomSDKAudioRawData *)data {}
- (void)onShareAudioRawDataReceived:(ZoomSDKAudioRawData *)data userID:(unsigned int)userID {}
- (void)onOneWayInterpreterAudioRawDataReceived:(ZoomSDKAudioRawData *)data strLanguageName:(NSString *)languageName {}
- (void)shutdown {
    if (self.stopping) return;
    self.stopping = YES;
    [self.participantTimer invalidate]; self.participantTimer = nil;
    [self.unmuteTimer invalidate]; self.unmuteTimer = nil;
    if (self.voice) {
        // Stop the sender before tearing down SDK objects. Keep the virtual source
        // installed until after leaving, so teardown cannot switch to a physical mic.
        bridge_set_sending(NO);
        bridge_set_sender(nil);
    }
    [self.audio unSubscribe]; self.audio.delegate = nil;
    ZoomSDKMeetingService *meeting = [[ZoomSDK sharedSDK] getMeetingService];
    if (self.recording) [meeting.getRecordController stopRawRecording];
    meeting.delegate = nil;
    meeting.getRecordController.delegate = nil;
    [meeting leaveMeetingWithCmd:LeaveMeetingCmd_Leave];
    [[ZoomSDK sharedSDK] unInitSDK];
    printf("RECEIVER_STOPPED exit=%d\n", self.exitCode);
    exit(self.exitCode);
}
- (NSApplicationTerminateReply)applicationShouldTerminate:(NSApplication *)sender {
    if (!self.stopping) [self shutdown];
    return NSTerminateNow;
}
@end

int main(int argc, const char *argv[]) {
    @autoreleasepool {
        setvbuf(stdout, NULL, _IONBF, 0);
        [NSApplication sharedApplication];
        [NSApp setActivationPolicy:NSApplicationActivationPolicyRegular];
        SparkieReceiver *receiver = [SparkieReceiver new];
        NSApp.delegate = receiver;
        signal(SIGTERM, SIG_IGN); signal(SIGINT, SIG_IGN);
        dispatch_source_t term = dispatch_source_create(DISPATCH_SOURCE_TYPE_SIGNAL, SIGTERM, 0, dispatch_get_main_queue());
        dispatch_source_t interrupt = dispatch_source_create(DISPATCH_SOURCE_TYPE_SIGNAL, SIGINT, 0, dispatch_get_main_queue());
        dispatch_source_set_event_handler(term, ^{ [receiver shutdown]; });
        dispatch_source_set_event_handler(interrupt, ^{ [receiver shutdown]; });
        dispatch_resume(term); dispatch_resume(interrupt);
        [NSApp run];
        return receiver.exitCode;
    }
}
