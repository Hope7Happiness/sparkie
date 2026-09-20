#import <Cocoa/Cocoa.h>
#import <ZoomSDK/ZoomSDK.h>

@interface AuthCheck : NSObject <NSApplicationDelegate, ZoomSDKAuthDelegate, ZoomSDKMeetingServiceDelegate>
@property(nonatomic, copy) NSString *token;
@property(nonatomic, strong) NSDictionary *meetingConfig;
@property(nonatomic) BOOL authenticated;
- (void)startAuth;
@end

@implementation AuthCheck
- (void)startAuth {
    ZoomSDKInitParams *params = [ZoomSDKInitParams new];
    params.zoomDomain = @"zoom.us";
    params.enableLog = NO;
    ZoomSDKError result = [[ZoomSDK sharedSDK] initSDKWithParams:params];
    printf("SDK_INIT=%ld\n", (long)result);
    fflush(stdout);
    if (result != ZoomSDKError_Success) exit(2);
    ZoomSDKAuthService *auth = [[ZoomSDK sharedSDK] getAuthService];
    auth.delegate = self;
    ZoomSDKAuthContext *context = [ZoomSDKAuthContext new];
    context.jwtToken = self.token;
    result = [auth sdkAuth:context];
    self.token = nil;
    printf("SDK_AUTH_REQUEST=%ld\n", (long)result);
    fflush(stdout);
    if (result != ZoomSDKError_Success) exit(3);
    dispatch_after(dispatch_time(DISPATCH_TIME_NOW, 45 * NSEC_PER_SEC), dispatch_get_main_queue(), ^{
        if (self.authenticated) return;
        fprintf(stderr, "SDK_AUTH_TIMEOUT: no callback within 45 seconds\n");
        exit(4);
    });
}
- (void)onZoomSDKAuthReturn:(ZoomSDKAuthError)result {
    printf("SDK_AUTH_RESULT=%ld\n", (long)result);
    fflush(stdout);
    self.authenticated = result == ZoomSDKAuthError_Success;
    if (self.authenticated && self.meetingConfig) {
        dispatch_async(dispatch_get_main_queue(), ^{
            ZoomSDKMeetingService *service = [[ZoomSDK sharedSDK] getMeetingService];
            service.delegate = self;
            ZoomSDKJoinMeetingElements *params = [ZoomSDKJoinMeetingElements new];
            params.userType = ZoomSDKUserType_WithoutLogin;
            params.meetingNumber = [self.meetingConfig[@"meeting_number"] longLongValue];
            params.password = self.meetingConfig[@"meeting_password"];
            params.displayName = self.meetingConfig[@"display_name"];
            params.isNoVideo = YES;
            params.isNoAudio = YES;
            ZoomSDKError joinResult = [service joinMeeting:params];
            printf("SDK_JOIN_REQUEST=%ld\n", (long)joinResult);
            fflush(stdout);
            if (joinResult != ZoomSDKError_Success) _Exit(7);
        });
        return;
    }
    dispatch_async(dispatch_get_main_queue(), ^{
        [[ZoomSDK sharedSDK] unInitSDK];
        _Exit(result == ZoomSDKAuthError_Success ? 0 : 5);
    });
}
- (void)onMeetingStatusChange:(ZoomSDKMeetingStatus)state meetingError:(ZoomSDKMeetingError)error EndReason:(EndMeetingReason)reason {
    printf("SDK_MEETING_STATUS=%ld ERROR=%ld REASON=%ld\n", (long)state, (long)error, (long)reason);
    fflush(stdout);
    if (state == ZoomSDKMeetingStatus_Failed) {
        dispatch_async(dispatch_get_main_queue(), ^{ [[ZoomSDK sharedSDK] unInitSDK]; _Exit(8); });
    }
}
- (void)onZoomAuthIdentityExpired {
    fprintf(stderr, "SDK_AUTH_EXPIRED\n");
    exit(6);
}
@end

int main(int argc, const char *argv[]) {
    @autoreleasepool {
        if (argc != 2 && argc != 3) return 1;
        NSString *token = [NSString stringWithContentsOfFile:@(argv[1]) encoding:NSUTF8StringEncoding error:nil];
        token = [token stringByTrimmingCharactersInSet:NSCharacterSet.whitespaceAndNewlineCharacterSet];
        if (!token.length) return 1;
        NSApplication *app = [NSApplication sharedApplication];
        [app setActivationPolicy:NSApplicationActivationPolicyProhibited];
        AuthCheck *delegate = [AuthCheck new];
        delegate.token = token;
        if (argc == 3) {
            NSData *data = [NSData dataWithContentsOfFile:@(argv[2])];
            if (!data) return 1;
            delegate.meetingConfig = [NSJSONSerialization JSONObjectWithData:data options:0 error:nil];
            if (!delegate.meetingConfig) return 1;
        }
        app.delegate = delegate;
        dispatch_async(dispatch_get_main_queue(), ^{ [delegate startAuth]; });
        [app run];
    }
    return 0;
}
