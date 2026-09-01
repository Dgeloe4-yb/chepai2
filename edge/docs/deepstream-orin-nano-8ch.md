# Jetson Orin Nano 8GB：8 路视频 + DeepStream 部署说明

目标：在 **统一内存 8GB** 上稳定运行 **8 路 RTSP** 解码 + **TensorRT/YOLO** 推理，并把结构化告警 POST 到管理端 `POST /api/alerts`。

## 1. 软件基线

1. 刷写与 Orin Nano 8GB 匹配的 **JetPack**（遵循 NVIDIA 官方该硬件支持矩阵，常见为 JetPack 5.1.x 或 6.x）。
2. 安装与 JetPack **成对版本**的 **DeepStream SDK**（见 NVIDIA DeepStream 发行说明中的依赖表）。
3. 确认 `nvidia-smi`（如可用）或 `jetson_release` 输出的 CUDA / TensorRT 版本与 DeepStream 要求一致。

## 2. 模型与 engine（必须在 aarch64 上生成）

1. 训练/导出 ONNX（可在 x86 上完成）：
   - `yolo export model=yolov8n.pt format=onnx opset=17 simplify=True`
2. 在 Orin Nano 本机转 TensorRT：
   - FP16 基线：`trtexec --onnx=yolov8n.onnx --saveEngine=yolov8n_fp16.engine --fp16`
   - **不要**复制 PC 上的 `.engine` 到 Jetson。
3. 算力不足时：再评估 INT8（需校准数据集）；或降低输入尺寸（例如 640→512）。

## 3. DeepStream 8 路管线要点

1. 使用 `uridecodebin` / `nvurisrcbin` 拉 RTSP，`nvstreammux` 合成 batch。
2. **batch-size=8** 与 **mux 宽高**决定显存/统一内存占用。Nano 8GB 建议：
   - 探测分辨率：`640×360`～`640×384` 或更低；
   - `nvvideoconvert` + `capsfilter` 统一格式后进入 `nvinfer`。
3. 用 `tegrastats` / `jtop` 观察 **RAM 与 SWAP**；出现 OOM 或大量丢帧时：
   - 降低 FPS（跳帧）：`interval` / `drop-frame-interval`；
   - 改为 **4+4 两批**分时推理；
   - **ROI 二级**：整条链只做车/人，**充电桩 ROI 裁剪**后再跑枪类小模型。

## 4. 二级 ROI 推理（充电枪乱放的推荐形态）

1. Primary `nvinfer`：COCO 车类或自训「车」检测，输出车体/车位关系。
2. 对 `roi_region.polygon_json` 映射到画面坐标后，在 probe 里裁切 `NvBufSurface` 子区域或小图送入 secondary GIE（检测 `gun`/`holster`）。
3. 小目标更清晰，但注意 **裁剪+二次推理的总时延**；可只对「枪 ROI」每隔 N 帧执行。

## 5. 与 Spring Boot 对接

1900~2000 字段 JSON 例：

```json
{
  "cameraId": 1,
  "alertType": "gun_misplace",
  "score": 0.81,
  "snapshotPath": "/data/alerts/cam1_xxx.jpg",
  "rawJson": { "trackId": 3, "det": [12, 34, 56, 78] }
}
```

边缘侧保存截图后，将 **可访问路径或 URL** 写入 `snapshotPath`；中心端当前入库为字符串。

## 6. systemd 守护

示例单元 `/etc/systemd/system/chepai-edge.service`：

```ini
[Unit]
Description=Chepai DeepStream edge
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=/opt/chepai-edge
Environment="GST_DEBUG=1"
ExecStart=/opt/nvidia/deepstream/deepstream/bin/deepstream-app -c deepstream_8ch.txt
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
```

启用：`sudo systemctl daemon-reload && sudo systemctl enable --now chepai-edge.service`

## 7. 运维清单

- **NTP** 校时（事件与录像对齐）。
- **日志切割**与 `journalctl` 大小限制。
- **磁盘**：告警截图目录 `logrotate` 或周期清理。
- **网络**：优先有线；RTSP 断流重连策略（DeepStream 源 bin 超时）。

以上内容与仓库内 `edge/poc/` 的桌面 PoC 逻辑一致，便于先在单路验证再迁移到 DeepStream 配置。
