# 自训练：充电枪 / 车型 / 车牌颜色（YOLO + TensorRT）指南

本指南配合仓库 `edge/poc/poc_pipeline.py` 的 **Ultralytics YOLO** 流程；训练在 PC GPU 完成，部署在 **Jetson Orin Nano 8GB** 本机转 **TensorRT**。

## 1. 数据采集

- **充电枪**：覆盖品牌、挂枪/插枪、近景/远景、白天夜间；每个桩位多角度。
- **车型**：如果只依赖 COCO，巴士/货车已覆盖一部分；若需区分「面包车 vs MPV」，需增补本地样本并加类。
- **车牌颜色**：优先同步记录 **蓝/绿/黄** 标签；雨天与强反光单独成集。

建议每类起步 **300～800** 张可用图（越少越要更强的数据增强与审核）。

## 2. 标注

1. 工具：**CVAT**、**Label Studio** 或 **LabelImg**（YOLO txt）。
2. 类别保持极简：
   - 枪线：`gun`、`holster`（枪座/挂钩）；
   OR `gun_in_slot` / `gun_out_slot` 二分类检测框。
3. 导出 **YOLOv8** 目录结构：

```
dataset/
  images/{train,val}/
  labels/{train,val}/
dataset.yaml
```

`dataset.yaml` 示例：

```yaml
path: .
train: images/train
val: images/val
names:
  0: gun
  1: holster
```

## 3. 训练（Ultralytics）

```bash
pip install -U ultralytics
yolo detect train model=yolov8n.pt data=dataset.yaml epochs=120 imgsz=640 batch=16 device=0 project=runs name=gun_det
```

技巧：

- 小目标：`imgsz` 可试 768（边缘侧要同步评估帧率）。
- 复制-粘贴增强、mosaic 对枪类有效；注意 **过增强** 会伤车牌颜色判断。
- 训练完：`yolo val model=runs/gun_det/weights/best.pt data=dataset.yaml`

## 4. 导出 ONNX

```bash
yolo export model=runs/gun_det/weights/best.pt format=onnx opset=17 simplify=True
```

## 5. Orin Nano 8GB 上转 TensorRT

在板子上：

```bash
/usr/local/tensorrt/bin/trtexec \
  --onnx=best.onnx \
  --saveEngine=gun_y8_fp16.engine \
  --fp16 \
  --workspace=4096
```

随后在 DeepStream `nvinfer` 配置中指向该 engine，并设置 **簇的输入尺寸与 batch** 与训练一致。

## 6. 上架前压测

1. `deepstream-app` 或自建 pipeline，统计 **`fps`、端到端延迟、RSS 内存`**。
2. 若 8 路达不到实时：
   - 优先 INT8 或更小模型（`yolov8n`→自定义剪枝）；
   - **ROI 二级**仅对充电桩区域跑枪模型；
   - 降低 `streammux` 输出分辨率或跳帧。

## 7. 与管理端字段映射

- `oil_car` / `gun_misplace` / `bad_park` / `non_sedan` 与 `POST /api/alerts` 中 `alertType` 对齐。
- `rawJson` 保存检测框、阈值版本、模型哈希，便于回放到具体一版权重。

## 8. 常见问题

- **误检枪**：多半是 ROI 过大或背景线缆干扰——缩 ROI 或增加负样本。
- **绿牌变蓝**：补光与阴影样本；或在上层加 **OCR/汉字** 约束。
- **斜停误判**：在 POC 中已提供 bbox+车位多边形启发式；上线可换 **OBB（旋转框）**。
