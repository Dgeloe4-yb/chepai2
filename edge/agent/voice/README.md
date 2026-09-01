# 现场语音素材（可选）
# 将下列 wav 放到工控机 /opt/chepai-edge/voice/ ，优先用 aplay/paplay 播放：
#   dual_slot.wav
#   car_in_bus_slot.wav
#   bad_park.wav
#   mini_ad.wav
#   non_sedan.wav
#   oil_car.wav
#
# 若无 wav，自动尝试 espeak-ng；都没有则仅打日志并按语速空等，保证队列仍顺序消费。
#
# 环境变量：
#   CHEPAI_VOICE_ENABLE=1
#   CHEPAI_VOICE_DIR=/opt/chepai-edge/voice
#   CHEPAI_VOICE_ENGINE=auto|wav|espeak|log
#   CHEPAI_VOICE_COOLDOWN_SEC=25
