// Local framed PCM bridge. Network I/O never runs inside the Zoom audio callback.
#include "VoiceBridge.h"
#include <arpa/inet.h>
#include <sys/socket.h>
#include <unistd.h>
#include <atomic>
#include <chrono>
#include <condition_variable>
#include <cstring>
#include <deque>
#include <fstream>
#include <iostream>
#include <mutex>
#include <thread>
#include <vector>
using namespace std;
using namespace ZOOMSDK;
namespace {
using Clock = chrono::steady_clock;
atomic<int> client{-1};
atomic<bool> sending{false}, playing{false};
atomic<unsigned> generation{0};
atomic<long long> gateUntil{0};
mutex outMutex, senderMutex, playMutex;
condition_variable outCV, playCV;
deque<vector<char>> outgoing;
vector<char> pending;
IZoomSDKAudioRawDataSender* sender = nullptr;
long long millis() { return chrono::duration_cast<chrono::milliseconds>(Clock::now().time_since_epoch()).count(); }
void fail() { int fd=client.load(); if(fd>=0) shutdown(fd, SHUT_RDWR); ++generation; }
void emit(char type, const char* data=nullptr, unsigned size=0) {
    if(client.load()<0) return;
    vector<char> packet(5+size); packet[0]=type;
    uint32_t n=htonl(size); memcpy(packet.data()+1,&n,4);
    if(size) memcpy(packet.data()+5,data,size);
    { lock_guard<mutex> lock(outMutex);
      if(outgoing.size()>=500) { fail(); return; }
      outgoing.push_back(move(packet)); }
    outCV.notify_one();
}
void error(const char* message) { emit('E', message, strlen(message)); }
bool transfer(int fd, char* data, size_t size, bool writing) {
    while(size) {
        auto n=writing ? send(fd,data,size,MSG_NOSIGNAL) : recv(fd,data,size,0);
        if(n<=0) return false;
        data+=n; size-=n;
    }
    return true;
}
void playback() {
    for(;;) {
        vector<char> data;
        unsigned gen;
        { unique_lock<mutex> lock(playMutex); playCV.wait(lock,[]{return !pending.empty();});
          data.swap(pending); gen=generation.load(); }
        bool ok=true;
        playing=true;
        auto next=Clock::now();
        for(size_t offset=4; offset<data.size(); offset+=1280) {
            if(gen!=generation.load()) { ok=false; break; }
            vector<char> chunk(1280,0);
            memcpy(chunk.data(),data.data()+offset,min(size_t(1280),data.size()-offset));
            SDKError result;
            { lock_guard<mutex> lock(senderMutex);
              if(!sender || !sending) { ok=false; break; }
              result=sender->send(chunk.data(),chunk.size(),32000,ZoomSDKAudioChannel_Mono); }
            if(result!=SDKERR_SUCCESS) { ok=false; break; }
            if(offset==4) emit('S',data.data(),4);
            next+=chrono::milliseconds(20);
            this_thread::sleep_until(next);
        }
        gateUntil=millis()+350;
        playing=false;
        if(ok) emit('D',data.data(),4);
        else if(gen==generation.load()) error("Zoom virtual microphone could not send audio");
    }
}
void serve() {
    ifstream file("/run/bridge-token"); string token; getline(file,token);
    if(token.size()!=64) { cerr<<"BRIDGE_TOKEN_INVALID"<<endl; return; }
    int server=socket(AF_INET,SOCK_STREAM,0), one=1;
    setsockopt(server,SOL_SOCKET,SO_REUSEADDR,&one,sizeof(one));
    sockaddr_in addr{}; addr.sin_family=AF_INET; addr.sin_port=htons(8769); addr.sin_addr.s_addr=INADDR_ANY;
    if(bind(server,(sockaddr*)&addr,sizeof(addr)) || listen(server,1)) { cerr<<"BRIDGE_LISTEN_FAILED"<<endl; return; }
    cout<<"BRIDGE_LISTENING"<<endl;
    for(;;) {
        int fd=accept(server,nullptr,nullptr); if(fd<0) continue;
        timeval timeout{5,0}; setsockopt(fd,SOL_SOCKET,SO_RCVTIMEO,&timeout,sizeof(timeout));
        setsockopt(fd,SOL_SOCKET,SO_SNDTIMEO,&timeout,sizeof(timeout));
        char auth[64];
        if(!transfer(fd,auth,64,false) || memcmp(auth,token.data(),64)) { close(fd); continue; }
        timeout={0,0}; setsockopt(fd,SOL_SOCKET,SO_RCVTIMEO,&timeout,sizeof(timeout));
        { lock_guard<mutex> lock(outMutex); outgoing.clear(); }
        client=fd;
        emit('H'); if(sending) emit('M');
        thread writer([fd]{
            for(;;) {
                vector<char> data;
                { unique_lock<mutex> lock(outMutex);
                  outCV.wait(lock,[]{return !outgoing.empty() || client.load()<0;});
                  if(client.load()<0) return;
                  data=move(outgoing.front()); outgoing.pop_front(); }
                if(!transfer(fd,data.data(),data.size(),true)) { fail(); return; }
            }
        });
        char header[5];
        while(transfer(fd,header,5,false)) {
            uint32_t size; memcpy(&size,header+1,4); size=ntohl(size);
            if(size>1920004) break;
            vector<char> payload(size);
            if(size && !transfer(fd,payload.data(),size,false)) break;
            if(header[0]=='C' && size==0) {
                ++generation; lock_guard<mutex> lock(playMutex); pending.clear();
            } else if(header[0]=='P' && size>4 && size%2==0) {
                lock_guard<mutex> lock(playMutex);
                if(playing || !pending.empty()) error("Playback is already active");
                else if(!sending) error("Zoom virtual microphone is muted or unavailable");
                else { pending=move(payload); playCV.notify_one(); }
            } else break;
        }
        fail(); client=-1; outCV.notify_all(); writer.join(); close(fd);
        { lock_guard<mutex> lock(playMutex); pending.clear(); }
    }
}
}
void bridgeStart() { thread(playback).detach(); thread(serve).detach(); }
void bridgeSender(IZoomSDKAudioRawDataSender* value) { lock_guard<mutex> lock(senderMutex); sender=value; }
void bridgeSending(bool value) { sending=value; if(value) emit('M'); else { ++generation; emit('N'); } }
void bridgeAudio(AudioRawData* audio) {
    if(client.load()<0) return;
    auto rate=audio->GetSampleRate(), channels=audio->GetChannelNum(), size=audio->GetBufferLen();
    if(channels!=1 || rate!=32000 || size%2 || size>64000) { error("Expected mono PCM16 32000 Hz from Zoom"); return; }
    vector<char> pcm(size,0);
    if(!playing && millis()>=gateUntil.load()) memcpy(pcm.data(),audio->GetBuffer(),size);
    emit('A',pcm.data(),pcm.size());
}
