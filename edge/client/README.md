# 车位边缘调试客户端（Flutter）

Windows / Android 桌面客户端：手动配置工控机地址 → 本地拉摄像头 RTSP → 从工控机拉推理结果叠加显示；支持**小广告画框**与**正停标定**。

## Flutter 命令卡住？

本机 Flutter 在 `Documents\Downloads\flutter_windows_3.41.6-stable`。访问官方源会超时，**务必先设国内镜像**再跑命令：

```powershell
$env:FLUTTER_STORAGE_BASE_URL = "https://storage.flutter-io.cn"
$env:PUB_HOSTED_URL = "https://pub.flutter-io.cn"
$flutter = "C:\Users\86183\Documents\Downloads\flutter_windows_3.41.6-stable\flutter\bin\flutter.bat"

& $flutter --no-version-check --version
```

可写入用户环境变量（永久）：

- `FLUTTER_STORAGE_BASE_URL` = `https://storage.flutter-io.cn`
- `PUB_HOSTED_URL` = `https://pub.flutter-io.cn`

不要在没有镜像时跑 `flutter` / `flutter create` / `flutter pub get`，否则会卡在 `github.com` / `storage.googleapis.com`。

## 运行客户端

```powershell
$env:FLUTTER_STORAGE_BASE_URL = "https://storage.flutter-io.cn"
$env:PUB_HOSTED_URL = "https://pub.flutter-io.cn"
$flutter = "C:\Users\86183\Documents\Downloads\flutter_windows_3.41.6-stable\flutter\bin\flutter.bat"

cd c:\Users\86183\Desktop\chepai2\edge\client
& $flutter --no-version-check pub get
& $flutter --no-version-check run -d windows
```

## 工控机端

生产服务 `chepai-edge` 已内嵌 Local API（默认 `0.0.0.0:8765`），无需单独 debug 进程：

```bash
sudo systemctl enable --now chepai-edge
```

客户端填写：`http://<工控机IP>:8765`（或 `http://chepai-rk3588:8765`）

### 客户端用到的 API

| 接口 | 说明 |
|------|------|
| `GET /api/state.json` | 相机列表（含 `rtspUrl`）、检测框、ROI、正停状态 |
| `POST /api/select-camera` | 切换相机 |
| `POST /api/rois` | 保存小广告区 `regionType=ad` |
| `DELETE /api/rois/{id}` | 删除 ROI |
| `POST /api/park-align/calib` | 正停标定（当前帧或 `imageBase64`） |
| `GET /api/preview.jpg` | RTSP 失败时的预览回退 |

## 使用流程

1. 填写工控机地址 → **连接**
2. 选相机（自动尝试 RTSP；失败则用工控机 JPEG 预览）
3. 画面上叠加：车 / 牌 / 广告 / 告警 / 停正连线
4. 工具栏「画框」→ 点选或拖广告区 → **保存广告区**
5. 「正停标定」：当前帧标定，或上传满排正停图

## 说明

- 视频流由**客户端直连摄像头 RTSP**；推理结果由工控机 `state.json` 轮询（约 2Hz）
- 若电脑访问不了摄像头内网，会自动回退到工控机 `/api/preview.jpg`
