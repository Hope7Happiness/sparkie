#include "ZoomSDKAudioRawData.h"
#include "VoiceBridge.h"
void ZoomSDKAudioRawData::onMixedAudioRawDataReceived(AudioRawData* audio) { bridgeAudio(audio); }
void ZoomSDKAudioRawData::onOneWayAudioRawDataReceived(AudioRawData*, uint32_t) {}
void ZoomSDKAudioRawData::onShareAudioRawDataReceived(AudioRawData*, uint32_t) {}
void ZoomSDKAudioRawData::onOneWayInterpreterAudioRawDataReceived(AudioRawData*, const zchar_t*) {}
