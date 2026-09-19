// Receive-only Zoom probe. No PCM, meeting credentials, or JWTs are logged.
#import <Cocoa/Cocoa.h>
#import <ZoomSDK/ZoomSDK.h>
#include <signal.h>
#include <stdint.h>

@interface SparkieReceiver : NSObject <NSApplicationDelegate, ZoomSDKAuthDelegate,
    ZoomSDKMeetingServiceDelegate, ZoomSDKMeetingRecordDelegate, ZoomSDKAudioRawDataDelegate>
@property NSDictionary *config;
@property ZoomSDKAudioRawDataHelper *audio;
@property BOOL recording;
@property BOOL requested;
@property BOOL stopping;
@property int exitCode;
@property unsigned long long frames;
@property unsigned long long bytes;
@property int peak;
- (void)shutdown;
@end

@implementation SparkieReceiver
- (void)applicationDidFinishLaunching:(NSNotification *)notification {
    ZoomSDKInitParams *params = [ZoomSDKInitParams new];
    params.zoomDomain = @"https://zoom.us";
    params.needCustomizedUI = NO;
    params.enableLog = NO;
    ZoomSDKError result = [[ZoomSDK sharedSDK] initSDKWithParams:params];
    printf("SDK_INIT result=%d\n", result);
    if (result != ZoomSDKError_Success) { self.exitCode = 1; [self shutdown]; return; }
    if ([NSProcessInfo.processInfo.arguments containsObject:@"--check"]) {
        printf("SDK_LOAD_CHECK_OK (no authentication or meeting join attempted)\n");
        [self shutdown]; return;
    }
    NSString *configPath = NSProcessInfo.processInfo.environment[@"SPARKIE_ZOOM_CONFIG"];
    NSData *data = configPath ? [NSData dataWithContentsOfFile:configPath] : nil;
    self.config = data ? [NSJSONSerialization JSONObjectWithData:data options:0 error:nil] : nil;
    if (![self.config isKindOfClass:NSDictionary.class]) { printf("CONFIG_MISSING_OR_INVALID\n"); self.exitCode = 1; [self shutdown]; return; }
    for (NSString *key in @[@"token", @"meeting_number", @"meeting_password", @"display_name"]) {
        if (![self.config[key] isKindOfClass:NSString.class] || ![self.config[key] length]) {
            printf("CONFIG_INVALID\n"); self.exitCode = 1; [self shutdown]; return;
        }
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
        printf("JOIN_VOIP result=%d\n", [actions actionMeetingWithCmd:ActionMeetingCmd_JoinVoip userID:0 onScreen:0]);
        [self tryAudio];
    } else if (state == ZoomSDKMeetingStatus_Failed) {
        self.exitCode = 1; [self shutdown];
    } else if (state == ZoomSDKMeetingStatus_Ended) {
        [self shutdown];
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
- (void)onMixedAudioRawDataReceived:(ZoomSDKAudioRawData *)data {
    const char *buffer = [data getBuffer];
    unsigned int size = [data getBufferLen];
    if (!buffer || !size) return;
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
- (void)onOneWayAudioRawDataReceived:(ZoomSDKAudioRawData *)data nodeID:(unsigned int)nodeID {}
- (void)onOneWayAudioRawDataReceived:(ZoomSDKAudioRawData *)data userID:(unsigned int)userID {}
- (void)onShareAudioRawDataReceived:(ZoomSDKAudioRawData *)data {}
- (void)onShareAudioRawDataReceived:(ZoomSDKAudioRawData *)data userID:(unsigned int)userID {}
- (void)onOneWayInterpreterAudioRawDataReceived:(ZoomSDKAudioRawData *)data strLanguageName:(NSString *)languageName {}
- (void)shutdown {
    if (self.stopping) return;
    self.stopping = YES;
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
