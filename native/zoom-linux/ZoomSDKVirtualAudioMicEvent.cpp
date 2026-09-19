#include "ZoomSDKVirtualAudioMicEvent.h"
#include "VoiceBridge.h"
#include <iostream>
ZoomSDKVirtualAudioMicEvent::ZoomSDKVirtualAudioMicEvent(std::string source) { pSender_=nullptr; }
void ZoomSDKVirtualAudioMicEvent::onMicInitialize(IZoomSDKAudioRawDataSender* sender) {
    pSender_=sender; bridgeSender(sender); std::cout<<"ZOOM_MIC_INITIALIZED"<<std::endl;
}
void ZoomSDKVirtualAudioMicEvent::onMicStartSend() { bridgeSending(true); std::cout<<"ZOOM_MIC_READY"<<std::endl; }
void ZoomSDKVirtualAudioMicEvent::onMicStopSend() { bridgeSending(false); }
void ZoomSDKVirtualAudioMicEvent::onMicUninitialized() { bridgeSending(false); bridgeSender(nullptr); pSender_=nullptr; }
