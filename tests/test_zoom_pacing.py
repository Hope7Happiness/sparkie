"""Exercise the real C++ playback loop with a deliberately stalled fake SDK."""
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


class ZoomPacingTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('c++'), 'C++ compiler required for native playback regression')
    def test_sdk_stall_does_not_cause_catchup_burst_or_drop_pcm(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as name:
            p = Path(name)
            (p / 'rawdata').mkdir()
            (p / 'rawdata/rawdata_audio_helper_interface.h').write_text('''
#pragma once
namespace ZOOMSDK {
enum SDKError { SDKERR_SUCCESS };
enum ZoomSDKAudioChannel { ZoomSDKAudioChannel_Mono };
struct IZoomSDKAudioRawDataSender {
 virtual SDKError send(char*, unsigned int, int, ZoomSDKAudioChannel) = 0;
};
}
''')
            (p / 'zoom_sdk_raw_data_def.h').write_text('''
#pragma once
struct AudioRawData {
 unsigned GetSampleRate() { return 32000; }
 unsigned GetChannelNum() { return 1; }
 unsigned GetBufferLen() { return 2; }
 char* GetBuffer() { static char data[2]{}; return data; }
};
''')
            for name in ('VoiceBridge.cpp', 'VoiceBridge.h'):
                shutil.copy(root / 'native/zoom-linux' / name, p / name)
            (p / 'test.cpp').write_text('''
#include "VoiceBridge.cpp"
#include <cstdlib>
struct FakeSender : IZoomSDKAudioRawDataSender {
 atomic<bool> entered{false};
 bool cancelTest=false;
 vector<Clock::time_point> times;
 vector<char> received;
 SDKError send(char* data, unsigned size, int rate, ZoomSDKAudioChannel channel) override {
   times.push_back(Clock::now()); received.insert(received.end(),data,data+size);
   if(cancelTest && times.size()==1) { entered=true; this_thread::sleep_for(chrono::milliseconds(100)); }
   // Stall inside the SDK for multiple frame periods. Old sleep_until catches up in a burst.
   if(times.size()==3) this_thread::sleep_for(chrono::milliseconds(75));
   return SDKERR_SUCCESS;
 }
};
int main(int argc, char**) {
 FakeSender fake;
 fake.cancelTest=argc>1;
 sender=&fake; sending=true; client=123;
 vector<char> expected(1280*10);
 for(size_t i=0;i<expected.size();++i) expected[i]=char(i%127);
 pending.resize(4+expected.size());
 uint32_t id=htonl(1); memcpy(pending.data(),&id,4);
 memcpy(pending.data()+4,expected.data(),expected.size());
 thread(playback).detach();
 if(fake.cancelTest) {
   while(!fake.entered) this_thread::sleep_for(chrono::milliseconds(1));
   vector<char> identifier(4); uint32_t cancel=htonl(77); memcpy(identifier.data(),&cancel,4);
   cancelPlayback(identifier);
   bool ack=false;
   for(int i=0;i<500 && !ack;++i) {
     this_thread::sleep_for(chrono::milliseconds(1));
     lock_guard<mutex> lock(outMutex);
     for(auto& p:outgoing) {
       if(p[0]=='E' || p[0]=='D') std::_Exit(5);
       if(p[0]=='K') {
         if(playing || memcmp(p.data()+5,identifier.data(),4) || fake.times.size()!=1) std::_Exit(6);
         ack=true;
       }
     }
     if(ack) outgoing.clear();
   }
   if(!ack) std::_Exit(7);
   { lock_guard<mutex> lock(playMutex);
     if(playing || !pending.empty()) std::_Exit(8);
     pending.resize(4+1280); uint32_t next=htonl(2); memcpy(pending.data(),&next,4); }
   playCV.notify_one();
 }
 bool completed=false;
 for(int i=0;i<500 && !completed;++i) {
   this_thread::sleep_for(chrono::milliseconds(10));
   lock_guard<mutex> lock(outMutex);
   for(auto& p:outgoing) if(p[0]=='D') completed=true;
 }
 if(!completed) std::_Exit(2);
 if(fake.cancelTest) { if(fake.times.size()!=2) std::_Exit(9); std::_Exit(0); }
 // D is emitted after the last SDK call, under outMutex; no more writes to fake state.
 if(fake.received!=expected || fake.times.size()!=10) std::_Exit(3);
 for(size_t i=1;i<fake.times.size();++i)
   if(fake.times[i]-fake.times[i-1]<chrono::milliseconds(5)) std::_Exit(4);
 std::_Exit(0);
}
''')
            build = subprocess.run(['c++', '-std=c++17', '-pthread', '-DMSG_NOSIGNAL=0', '-I', str(p),
                            str(p / 'test.cpp'), '-o', str(p / 'test')], capture_output=True, text=True)
            self.assertEqual(build.returncode, 0, build.stderr)
            result = subprocess.run([str(p / 'test')], capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            result = subprocess.run([str(p / 'test'), 'cancel'], capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
