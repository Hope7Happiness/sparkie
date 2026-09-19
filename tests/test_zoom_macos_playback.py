"""Run the actual macOS bridge loop against a fake sender, with no Zoom SDK."""
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class MacPlaybackTests(unittest.TestCase):
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
