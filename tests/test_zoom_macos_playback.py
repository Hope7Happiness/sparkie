"""Run the actual macOS bridge loop against a fake sender, with no Zoom SDK."""
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class MacPlaybackTests(unittest.TestCase):
    @unittest.skipUnless(sys.platform == 'darwin' and shutil.which('clang'), 'macOS clang required')
    def test_workspace_snapshot_pixels_and_bounded_lifecycle(self):
        root = Path(__file__).resolve().parents[1]
        native = (root / 'native/zoom-macos/main.m').read_text()
        method = '- (void)captureShareFrame {' + native.split('- (void)captureShareFrame {', 1)[1].split(
            '// Virtual microphone callbacks', 1)[0]
        harness = r'''
#import <Cocoa/Cocoa.h>
#import <WebKit/WebKit.h>
typedef int ZoomSDKError;
enum { ZoomSDKError_Success = 0, ZoomSDKFrameDataFormat_I420_Limited = 0 };
static int frames;
@interface ZoomSDKShareSender : NSObject
- (int)sendShareFrame:(char*)data width:(unsigned)w height:(unsigned)h frameLength:(unsigned)n format:(int)format;
@end
@implementation ZoomSDKShareSender
- (int)sendShareFrame:(char*)data width:(unsigned)w height:(unsigned)h frameLength:(unsigned)n format:(int)format {
    if (w != 1280 || h != 720 || n != w * h * 3 / 2 || format != 0) _Exit(10);
    unsigned char *p = (unsigned char *)data;
    for (unsigned i = 0; i < w * h; ++i) if (p[i] != 235) _Exit(11);
    for (unsigned i = w * h; i < n; ++i) if (p[i] != 128) _Exit(12);
    frames++;
    return 0;
}
@end
@interface View : NSObject
@property(copy) void (^completion)(NSImage *, NSError *);
@property int requests;
- (NSRect)bounds;
- (void)takeSnapshotWithConfiguration:(WKSnapshotConfiguration *)configuration completionHandler:(void (^)(NSImage *, NSError *))callback;
- (void)complete:(NSImage *)image;
@end
@implementation View
- (NSRect)bounds { return NSMakeRect(0, 0, 1280, 720); }
- (void)takeSnapshotWithConfiguration:(WKSnapshotConfiguration *)configuration completionHandler:(void (^)(NSImage *, NSError *))callback {
    self.requests++;
    self.completion = callback;
}
- (void)complete:(NSImage *)image {
    void (^callback)(NSImage *, NSError *) = self.completion;
    self.completion = nil;
    callback(image, nil);
}
@end
@interface Receiver : NSObject
@property ZoomSDKShareSender *shareSender;
@property View *shareView;
@property NSMutableData *shareI420;
@property BOOL shareSnapshotPending;
@property BOOL stopping;
- (void)captureShareFrame;
@end
@implementation Receiver
''' + method + r'''
@end
int main() {
    @autoreleasepool {
        NSBitmapImageRep *rep = [[NSBitmapImageRep alloc] initWithBitmapDataPlanes:NULL
            pixelsWide:16 pixelsHigh:16 bitsPerSample:8 samplesPerPixel:4 hasAlpha:YES
            isPlanar:NO colorSpaceName:NSDeviceRGBColorSpace bitmapFormat:0 bytesPerRow:64 bitsPerPixel:32];
        memset(rep.bitmapData, 255, 16 * 64);
        NSImage *image = [[NSImage alloc] initWithSize:NSMakeSize(16, 16)];
        [image addRepresentation:rep];
        Receiver *receiver = [Receiver new];
        receiver.shareSender = [ZoomSDKShareSender new];
        receiver.shareView = [View new];
        [receiver captureShareFrame];
        [receiver captureShareFrame];
        if (receiver.shareView.requests != 1) return 13;
        [receiver.shareView complete:image];
        if (frames != 1 || receiver.shareSnapshotPending) return 14;
        [receiver captureShareFrame];
        receiver.shareSender = [ZoomSDKShareSender new];
        [receiver.shareView complete:image];
        if (frames != 1) return 15;
        [receiver captureShareFrame];
        [receiver.shareView complete:nil];
        if (frames != 1 || receiver.shareSnapshotPending) return 16;
        [receiver captureShareFrame];
        receiver.stopping = YES;
        [receiver.shareView complete:image];
        [receiver captureShareFrame];
        if (frames != 1 || receiver.shareView.requests != 4) return 17;
    }
    return 0;
}
'''
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'snapshot.m'
            binary = Path(directory) / 'snapshot'
            source.write_text(harness)
            build = subprocess.run(['clang', '-fobjc-arc', '-fblocks', '-framework', 'Cocoa',
                                    '-framework', 'WebKit', str(source), '-o', str(binary)],
                                   capture_output=True, text=True, timeout=30)
            self.assertEqual(build.returncode, 0, build.stderr)
            result = subprocess.run([str(binary)], capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)

    @unittest.skipUnless(sys.platform == 'darwin' and shutil.which('clang'), 'macOS clang required')
    def test_packets_stall_and_sdk_rejection(self):
        root = Path(__file__).resolve().parents[1]
        source = (root / 'native/zoom-macos/main.m').read_text().split('@interface SparkieReceiver')[0]
        source = source.replace('#import <ZoomSDK/ZoomSDK.h>', '').replace(
            '#import <ZoomSDK/ZoomSDKRawDataAudioSourceController.h>', '''
typedef int ZoomSDKError;
enum { ZoomSDKError_Success = 0, ZoomSDKAudioChannel_Mono = 0 };
@interface ZoomSDKAudioRawDataSender : NSObject
- (int)send:(char*)data dataLength:(unsigned)length sampleRate:(int)rate channel:(int)channel;
@end
@interface ZoomSDKAudioRawData : NSObject
- (const char*)getBuffer;
- (unsigned)getSampleRate;
- (unsigned)getChannelNum;
- (unsigned)getBufferLen;
- (long long)getTimeStamp;
@end
''')
        harness = r'''
static int calls, mode;
static _Atomic int entered = 0;
static long long ended;
static NSMutableData *received;
@implementation ZoomSDKAudioRawDataSender
- (int)send:(char*)data dataLength:(unsigned)length sampleRate:(int)rate channel:(int)channel {
    if (length != 1280 || rate != 32000 || channel != 0) _Exit(10);
    if (ended && bridge_millis() - ended < 10) _Exit(11);
    ++calls;
    if (mode == 3 && calls == 1) { entered = 1; usleep(100000); }
    if (mode == 1 && calls == 3) return 20; // PreprocessRawdataError in installed header.
    [received appendBytes:data length:length];
    if (mode == 0 && calls == 2) usleep(75000);
    ended = bridge_millis();
    return 0;
}
@end
int main(int argc, char **argv) {
    mode = atoi(argv[1]);
    bridge_client = 123; bridge_sending = YES;
    bridge_sender = [ZoomSDKAudioRawDataSender new];
    bridge_outgoing = [NSMutableArray new]; received = [NSMutableData new];
    if (mode == 2) bridge_sender = nil;
    pthread_t thread; pthread_create(&thread, NULL, bridge_playback, NULL);
    for (unsigned id = 1; id <= 2; ++id) {
        // Full frames followed by a partial frame; then a very short packet.
        unsigned size = id == 1 ? 1280 * 4 + 22 : 2;
        NSMutableData *data = [NSMutableData dataWithLength:size + 4];
        uint32_t wire = htonl(id); memcpy(data.mutableBytes, &wire, 4);
        memset((char*)data.mutableBytes + 4, 7, size);
        pthread_mutex_lock(&play_mutex); bridge_pending = data;
        pthread_mutex_unlock(&play_mutex); pthread_cond_signal(&play_cv);
        if (mode == 3 && id == 1) {
            while (!entered) usleep(1000);
            uint32_t cancel = htonl(77);
            bridge_cancel([NSData dataWithBytes:&cancel length:4]);
        }
        BOOL done = NO;
        for (int i = 0; i < 1000 && !done; ++i) {
            usleep(1000);
            pthread_mutex_lock(&out_mutex);
            for (NSData *packet in bridge_outgoing) {
                const char *bytes = packet.bytes;
                if (bytes[0] == 'E') {
                    NSDictionary *error = [NSJSONSerialization JSONObjectWithData:
                        [packet subdataWithRange:NSMakeRange(5, packet.length - 5)] options:0 error:nil];
                    if (mode == 1 && [error[@"reason"] isEqual:@"sdk_send_failed"] &&
                        [error[@"sdk_result"] intValue] == 20 && [error[@"frame_index"] intValue] == 3 && calls == 3) _Exit(0);
                    if (mode == 2 && [error[@"reason"] isEqual:@"microphone_unavailable"] &&
                        [error[@"sdk_result"] intValue] == -1 && calls == 0) _Exit(0);
                    _Exit(12);
                }
                if (bytes[0] == 'D') {
                    if (mode == 3 && id == 1) _Exit(16);
                    done = YES;
                }
                if (bytes[0] == 'K') {
                    uint32_t cancel; memcpy(&cancel, bytes + 5, 4);
                    if (mode != 3 || id != 1 || ntohl(cancel) != 77 || bridge_playing || calls != 1) _Exit(17);
                    done = YES;
                }
            }
            if (done) [bridge_outgoing removeAllObjects];
            pthread_mutex_unlock(&out_mutex);
        }
        if (!done || (mode && mode != 3)) _Exit(13);
    }
    if (mode == 3) { if (calls != 2) _Exit(18); _Exit(0); }
    if (calls != 6 || received.length != 1280 * 6) _Exit(14);
    const unsigned char *p = received.bytes;
    for (unsigned i = 0; i < received.length; ++i) {
        unsigned char expected = (i < 1280 * 4 + 22 || (i >= 1280 * 5 && i < 1280 * 5 + 2)) ? 7 : 0;
        if (p[i] != expected) _Exit(15);
    }
    _Exit(0);
}
'''
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            (path / 'test.m').write_text(source + harness)
            build = subprocess.run(['clang', '-fobjc-arc', '-fblocks', '-framework', 'Cocoa',
                                    str(path / 'test.m'), '-o', str(path / 'test')], capture_output=True, text=True)
            self.assertEqual(build.returncode, 0, build.stderr)
            for mode in ('0', '1', '2', '3'):
                with self.subTest(mode=mode):
                    result = subprocess.run([str(path / 'test'), mode], capture_output=True, text=True, timeout=5)
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
