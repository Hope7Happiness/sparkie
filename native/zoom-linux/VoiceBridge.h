#pragma once
#include "rawdata/rawdata_audio_helper_interface.h"
#include "zoom_sdk_raw_data_def.h"
void bridgeStart();
void bridgeAudio(AudioRawData* audio);
void bridgeSender(ZOOMSDK::IZoomSDKAudioRawDataSender* sender);
void bridgeSending(bool enabled);
