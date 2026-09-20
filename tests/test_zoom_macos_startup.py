"""Exercise native admission configuration without loading Zoom or opening audio."""
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class NativeStartupTests(unittest.TestCase):
    @unittest.skipUnless(sys.platform == 'darwin' and shutil.which('clang'), 'macOS clang required')
    def test_voice_admission_defers_audio_and_configuration_errors_stop_join(self):
        native = (Path(__file__).resolve().parents[1] / 'native/zoom-macos/main.m').read_text()
        method = '- (void)onZoomSDKAuthReturn:' + native.split(
            '- (void)onZoomSDKAuthReturn:', 1)[1].split('- (void)onZoomAuthIdentityExpired', 1)[0]
        harness = r'''
#import <Foundation/Foundation.h>
typedef int ZoomSDKAuthError;
typedef int ZoomSDKError;
enum { ZoomSDKAuthError_Success = 0, ZoomSDKError_Success = 0, ZoomSDKUserType_WithoutLogin = 0 };
static BOOL autoAudio, muted, noAudio;
static int configError, joins;
@interface ZoomSDKAudioSetting : NSObject
- (int)enableMuteMicJoinVoip:(BOOL)value;
- (int)enableAutoJoinVoip:(BOOL)value;
@end
@implementation ZoomSDKAudioSetting
- (int)enableMuteMicJoinVoip:(BOOL)value { muted = value; return 0; }
- (int)enableAutoJoinVoip:(BOOL)value { autoAudio = value; return configError; }
@end
@interface Settings : NSObject
- (ZoomSDKAudioSetting *)getAudioSetting;
@end
@implementation Settings
- (ZoomSDKAudioSetting *)getAudioSetting { return [ZoomSDKAudioSetting new]; }
@end
@interface ZoomSDKJoinMeetingElements : NSObject
@property int userType;
@property long long meetingNumber;
@property NSString *password;
@property NSString *displayName;
@property BOOL isNoVideo;
@property BOOL isNoAudio;
@end
@implementation ZoomSDKJoinMeetingElements
@end
@interface Recorder : NSObject
@property id delegate;
@end
@implementation Recorder
@end
@interface ZoomSDKMeetingService : NSObject
@property id delegate;
- (Recorder *)getRecordController;
- (int)joinMeeting:(ZoomSDKJoinMeetingElements *)join;
@end
@implementation ZoomSDKMeetingService
- (Recorder *)getRecordController { return [Recorder new]; }
- (int)joinMeeting:(ZoomSDKJoinMeetingElements *)join {
    joins++; noAudio = join.isNoAudio;
    if (!muted || !join.isNoVideo || join.meetingNumber != 123456789) _Exit(10);
    return 0;
}
@end
@interface ZoomSDK : NSObject
+ (ZoomSDK *)sharedSDK;
- (Settings *)getSettingService;
- (ZoomSDKMeetingService *)getMeetingService;
@end
@implementation ZoomSDK
+ (ZoomSDK *)sharedSDK { return [ZoomSDK new]; }
- (Settings *)getSettingService { return [Settings new]; }
- (ZoomSDKMeetingService *)getMeetingService { return [ZoomSDKMeetingService new]; }
@end
@interface Receiver : NSObject
@property NSDictionary *config;
@property BOOL voice;
@property int exitCode;
@property BOOL stopped;
- (void)shutdown;
@end
@implementation Receiver
- (void)shutdown { self.stopped = YES; }
''' + method + r'''
@end
int main() {
    @autoreleasepool {
        for (int mode = 0; mode < 3; mode++) {
            Receiver *receiver = [Receiver new];
            receiver.voice = mode != 1;
            receiver.config = @{ @"token": @"synthetic", @"meeting_number": @"123456789",
                                 @"meeting_password": @"synthetic", @"display_name": @"Sparkie" };
            joins = 0; configError = mode == 2 ? 8 : 0;
            [receiver onZoomSDKAuthReturn:0];
            if (mode == 2) {
                if (joins || !receiver.stopped || receiver.exitCode != 1) return 11;
            } else {
                if (joins != 1 || receiver.stopped) return 12;
                // Voice admission must not initialize local audio before the
                // InMeeting callback can install the external microphone.
                if (mode == 0 && (autoAudio || !noAudio)) return 13;
                // The receive-only probe retains its original auto-audio mode.
                if (mode == 1 && (!autoAudio || noAudio)) return 14;
            }
        }
    }
    return 0;
}
'''
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'startup.m'
            binary = Path(directory) / 'startup'
            source.write_text(harness)
            built = subprocess.run(['clang', '-fobjc-arc', '-framework', 'Foundation',
                                    str(source), '-o', str(binary)], capture_output=True, text=True, timeout=30)
            self.assertEqual(built.returncode, 0, built.stderr)
            result = subprocess.run([str(binary)], capture_output=True, text=True, timeout=5)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
