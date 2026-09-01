import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';
import 'dart:ui' as ui;

import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;
import 'package:path_provider/path_provider.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:video_player/video_player.dart';

void main() {
  WidgetsFlutterBinding.ensureInitialized();
  runApp(const ChepaiApp());
}

/// BoxFit.contain 下：预览区局部坐标 ↔ 归一化图像坐标（与 OverlayPainter 一致）。
({double scale, double ox, double oy, double dw, double dh}) previewContainLayout(
  Size viewSize,
  double displayW,
  double displayH,
) {
  final scale = (viewSize.width / displayW < viewSize.height / displayH)
      ? viewSize.width / displayW
      : viewSize.height / displayH;
  final dw = displayW * scale;
  final dh = displayH * scale;
  final ox = (viewSize.width - dw) / 2;
  final oy = (viewSize.height - dh) / 2;
  return (scale: scale, ox: ox, oy: oy, dw: dw, dh: dh);
}

/// 点击落在 letterbox 黑边上时返回 null。
Offset? localToNormInContain(
  Offset local,
  Size viewSize,
  double displayW,
  double displayH,
) {
  if (displayW <= 0 || displayH <= 0 || viewSize.isEmpty) return null;
  final layout = previewContainLayout(viewSize, displayW, displayH);
  if (local.dx < layout.ox ||
      local.dy < layout.oy ||
      local.dx > layout.ox + layout.dw ||
      local.dy > layout.oy + layout.dh) {
    return null;
  }
  final nx = ((local.dx - layout.ox) / layout.dw).clamp(0.0, 1.0);
  final ny = ((local.dy - layout.oy) / layout.dh).clamp(0.0, 1.0);
  return Offset(nx, ny);
}

class ChepaiApp extends StatelessWidget {
  const ChepaiApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: '车位边缘客户端',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        colorScheme: ColorScheme.fromSeed(
          seedColor: const Color(0xFF1B6B4A),
          brightness: Brightness.dark,
        ),
        useMaterial3: true,
      ),
      home: const HomePage(),
    );
  }
}

class EdgeApi {
  EdgeApi(this.baseUrl);

  String baseUrl;

  Uri _u(String path) => Uri.parse('${baseUrl.replaceAll(RegExp(r"/+$"), "")}$path');

  Future<Map<String, dynamic>> getState() async {
    final res = await http.get(_u('/api/state.json')).timeout(const Duration(seconds: 5));
    if (res.statusCode != 200) {
      throw Exception('state ${res.statusCode}');
    }
    return jsonDecode(utf8.decode(res.bodyBytes)) as Map<String, dynamic>;
  }

  Future<void> selectCamera(int id) async {
    final res = await http.post(
      _u('/api/select-camera'),
      headers: {'Content-Type': 'application/json'},
      body: jsonEncode({'cameraId': id}),
    );
    if (res.statusCode != 200) throw Exception('selectCamera failed');
  }

  Future<void> refreshConfig() async {
    await http.post(_u('/api/refresh-config'));
  }

  /// 把摄像头 RTSP 主机写到工控机本地配置，并立即重连。
  Future<Map<String, dynamic>> updateCameraIp({
    required int cameraId,
    required String host,
    int? port,
    String? username,
    String? password,
    int? channel,
  }) async {
    final body = <String, dynamic>{
      'cameraId': cameraId,
      'host': host.trim(),
    };
    if (port != null) body['port'] = port;
    if (username != null && username.isNotEmpty) body['username'] = username;
    if (password != null) body['password'] = password;
    if (channel != null) body['channel'] = channel;
    final res = await http
        .post(
          _u('/api/camera-ip'),
          headers: {'Content-Type': 'application/json'},
          body: jsonEncode(body),
        )
        .timeout(const Duration(seconds: 20));
    final map = jsonDecode(utf8.decode(res.bodyBytes)) as Map<String, dynamic>;
    if (res.statusCode != 200) {
      throw Exception(map['error'] ?? 'update camera ip failed');
    }
    return map;
  }

  Future<int> saveRoi({
    required int cameraId,
    required List<List<double>> polygon,
    required String regionType,
    String name = '',
  }) async {
    final res = await http.post(
      _u('/api/rois'),
      headers: {'Content-Type': 'application/json'},
      body: jsonEncode({
        'cameraId': cameraId,
        'regionType': regionType,
        'polygon': polygon,
        'name': name.isEmpty
            ? (regionType == 'parking' ? 'slot' : 'ad_zone')
            : name,
        'normalized': true,
      }),
    );
    if (res.statusCode != 201) {
      throw Exception('save roi: ${res.body}');
    }
    final map = jsonDecode(res.body) as Map<String, dynamic>;
    final id = map['id'];
    if (id is int) return id;
    if (id is num) return id.toInt();
    return 0;
  }

  Future<int> saveAdRoi({
    required int cameraId,
    required List<List<double>> polygon,
    String name = 'ad_zone',
  }) =>
      saveRoi(cameraId: cameraId, polygon: polygon, regionType: 'ad', name: name);

  Future<int> saveParkingRoi({
    required int cameraId,
    required List<List<double>> polygon,
    String name = 'slot',
  }) =>
      saveRoi(cameraId: cameraId, polygon: polygon, regionType: 'parking', name: name);

  Future<int> saveBusRoi({
    required int cameraId,
    required List<List<double>> polygon,
    String name = 'bus',
  }) =>
      saveRoi(cameraId: cameraId, polygon: polygon, regionType: 'bus', name: name);

  Future<void> deleteRoi(int id) async {
    final res = await http.delete(_u('/api/rois/$id'));
    if (res.statusCode != 204 && res.statusCode != 200) {
      throw Exception('delete roi: ${res.statusCode} ${res.body}');
    }
  }

  Future<Map<String, dynamic>> calibParkAlign({
    String? imageBase64,
    double dxThreshold = 0.15,
  }) async {
    final body = <String, dynamic>{'dxThreshold': dxThreshold};
    if (imageBase64 != null) body['imageBase64'] = imageBase64;
    final res = await http.post(
      _u('/api/park-align/calib'),
      headers: {'Content-Type': 'application/json'},
      body: jsonEncode(body),
    );
    final map = jsonDecode(utf8.decode(res.bodyBytes)) as Map<String, dynamic>;
    if (res.statusCode != 200) {
      throw Exception(map['error'] ?? 'calib failed');
    }
    return map;
  }

  Future<Uint8List?> previewJpeg() async {
    final res = await http.get(_u('/api/preview.jpg')).timeout(const Duration(seconds: 3));
    if (res.statusCode != 200) return null;
    return res.bodyBytes;
  }

  Future<Map<String, dynamic>> inferImage(Uint8List bytes, {bool useRois = true}) async {
    final res = await http
        .post(
          _u('/api/infer/image'),
          headers: {'Content-Type': 'application/json'},
          body: jsonEncode({
            'imageBase64': base64Encode(bytes),
            'useRois': useRois,
          }),
        )
        .timeout(const Duration(minutes: 2));
    final map = jsonDecode(utf8.decode(res.bodyBytes)) as Map<String, dynamic>;
    if (res.statusCode != 200) throw Exception(map['error'] ?? 'infer image failed');
    return map;
  }

  Future<Map<String, dynamic>> inferVideo(
    Uint8List bytes, {
    String filename = 'upload.mp4',
    int everyN = 15,
    int maxFrames = 300,
  }) async {
    final req = http.MultipartRequest('POST', _u('/api/infer/video'))
      ..files.add(http.MultipartFile.fromBytes('file', bytes, filename: filename));
    final streamed = await req.send().timeout(const Duration(minutes: 10));
    final res = await http.Response.fromStream(streamed);
    final map = jsonDecode(utf8.decode(res.bodyBytes)) as Map<String, dynamic>;
    if (res.statusCode != 200) throw Exception(map['error'] ?? 'infer video failed');
    return map;
  }
}

String alertTypeLabel(String? type) {
  switch (type) {
    case 'mini_ad':
      return '小广告';
    case 'bad_park':
      return '停歪';
    case 'oil_car':
      return '非绿牌进油区';
    case 'bus_in_restricted':
    case 'non_sedan':
      return '公交车进入限制区域';
    case 'dual_slot':
      return '占两车位';
    case 'car_in_bus_slot':
      return '轿车占公交位';
    default:
      return type ?? '未知';
  }
}

Color alertTypeColor(String? type) {
  switch (type) {
    case 'mini_ad':
      return Colors.redAccent;
    case 'bad_park':
      return Colors.orangeAccent;
    case 'oil_car':
      return Colors.deepPurpleAccent;
    case 'bus_in_restricted':
    case 'non_sedan':
      return Colors.amberAccent;
    case 'dual_slot':
      return Colors.deepOrangeAccent;
    case 'car_in_bus_slot':
      return Colors.orangeAccent;
    default:
      return Colors.blueGrey;
  }
}

int _detectionCount(Map<String, dynamic>? dets) {
  if (dets == null) return 0;
  return ((dets['vehicles'] as List?)?.length ?? 0) +
      ((dets['plates'] as List?)?.length ?? 0) +
      ((dets['mini_ads'] as List?)?.length ?? 0) +
      ((dets['alerts'] as List?)?.length ?? 0);
}

class HomePage extends StatefulWidget {
  const HomePage({super.key});

  @override
  State<HomePage> createState() => _HomePageState();
}

enum DrawMode { none, adRoi, parkingRoi, busRoi }

class _HomePageState extends State<HomePage> {
  final _hostCtrl = TextEditingController(text: 'http://chepai-rk3588:8765');
  EdgeApi? _api;
  Timer? _poll;
  Map<String, dynamic>? _state;
  String? _error;
  DrawMode _drawMode = DrawMode.none;
  final List<Offset> _draftNorm = [];
  Uint8List? _previewBytes;
  bool _busy = false;
  String? _inferNote;
  Map<String, dynamic>? _overlayDetections;
  List<Map<String, dynamic>> _videoTimeline = [];
  String? _inferVideoUrl;
  bool _videoDialogOpen = false;
  bool _videoLoading = false;
  String? _videoError;
  VideoPlayerController? _videoController;
  double _coordFrameW = 1280;
  double _coordFrameH = 720;
  double _displayFrameW = 1280;
  double _displayFrameH = 720;
  bool _inferAnnotated = false;

  @override
  void initState() {
    super.initState();
    _loadSettings();
  }

  Future<void> _loadSettings() async {
    final prefs = await SharedPreferences.getInstance();
    final host = prefs.getString('edge_host');
    if (host != null && host.isNotEmpty) {
      _hostCtrl.text = host;
    }
  }

  Future<void> _saveHost() async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString('edge_host', _hostCtrl.text.trim());
  }

  @override
  void dispose() {
    _poll?.cancel();
    _videoController?.dispose();
    _hostCtrl.dispose();
    super.dispose();
  }

  Future<(double, double)> _jpegSize(Uint8List bytes) async {
    final codec = await ui.instantiateImageCodec(bytes);
    final frame = await codec.getNextFrame();
    final img = frame.image;
    final size = (img.width.toDouble(), img.height.toDouble());
    img.dispose();
    return size;
  }

  Future<void> _setPreviewBytes(
    Uint8List bytes, {
    double? coordW,
    double? coordH,
    bool annotated = false,
  }) async {
    final (dw, dh) = await _jpegSize(bytes);
    if (!mounted) return;
    setState(() {
      _previewBytes = bytes;
      _displayFrameW = dw;
      _displayFrameH = dh;
      if (coordW != null) _coordFrameW = coordW;
      if (coordH != null) _coordFrameH = coordH;
      _inferAnnotated = annotated;
    });
  }

  void _syncCoordFromState(Map<String, dynamic>? state) {
    final cw = (state?['frameW'] as num?)?.toDouble();
    final ch = (state?['frameH'] as num?)?.toDouble();
    final dw = (state?['displayFrameW'] as num?)?.toDouble();
    final dh = (state?['displayFrameH'] as num?)?.toDouble();
    if (cw != null && cw > 0) _coordFrameW = cw;
    if (ch != null && ch > 0) _coordFrameH = ch;
    if (dw != null && dw > 0) _displayFrameW = dw;
    if (dh != null && dh > 0) _displayFrameH = dh;
  }

  Map<String, dynamic>? _effectiveDetections(Map<String, dynamic>? state) {
    final live = state?['detections'] as Map<String, dynamic>?;
    if (live != null && _detectionCount(live) > 0) return live;
    return _overlayDetections ?? live;
  }

  Future<void> _disposeVideoPlayer() async {
    await _videoController?.dispose();
    _videoController = null;
  }

  Future<void> _openInferVideo(String videoUrl) async {
    final api = _api;
    if (api == null) return;
    setState(() {
      _videoLoading = true;
      _videoError = null;
    });
    final base = api.baseUrl.replaceAll(RegExp(r'/+$'), '');
    final uri = Uri.parse('$base$videoUrl').replace(
      queryParameters: {'t': '${DateTime.now().millisecondsSinceEpoch}'},
    );
    await _disposeVideoPlayer();
    try {
      final res = await http.get(uri).timeout(const Duration(minutes: 3));
      if (res.statusCode != 200) {
        throw Exception('HTTP ${res.statusCode}');
      }
      final dir = await getTemporaryDirectory();
      final file = File('${dir.path}/chepai_infer_latest.mp4');
      await file.writeAsBytes(res.bodyBytes, flush: true);
      final controller = VideoPlayerController.file(file);
      _videoController = controller;
      await controller.initialize();
      await controller.setLooping(true);
      controller.addListener(() {
        if (mounted) setState(() {});
      });
      if (!mounted) return;
      setState(() {
        _videoLoading = false;
        _videoError = null;
      });
      await controller.play();
    } catch (e) {
      await _disposeVideoPlayer();
      if (mounted) {
        setState(() {
          _videoLoading = false;
          _videoError = '$e';
        });
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('推理视频加载失败: $e（可点下方按钮重试）')),
        );
      }
    }
  }

  Future<void> _pauseInferVideo() async {
    await _videoController?.pause();
  }

  int _alertCount(Map<String, dynamic>? dets) {
    final current = (dets?['alerts'] as List?)?.length ?? 0;
    final timeline = _videoTimeline.fold<int>(
      0,
      (sum, item) => sum + (((item['alerts'] as List?)?.length) ?? 0),
    );
    return current + timeline;
  }

  Future<void> _showAlertsDialog(Map<String, dynamic>? dets) async {
    await showDialog<void>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('告警记录'),
        content: SizedBox(
          width: 520,
          height: 420,
          child: _buildAlertsContent(dets),
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx), child: const Text('关闭')),
        ],
      ),
    );
  }

  Future<void> _showVideoDialog() async {
    if (_inferVideoUrl == null) return;
    if (_videoController == null && !_videoLoading) {
      await _openInferVideo(_inferVideoUrl!);
    }
    if (!mounted) return;
    setState(() => _videoDialogOpen = true);
    await showDialog<void>(
      context: context,
      builder: (ctx) {
        return StatefulBuilder(
          builder: (context, setDialogState) {
            void refreshDialog() {
              if (context.mounted) setDialogState(() {});
            }
            _videoController?.removeListener(refreshDialog);
            _videoController?.addListener(refreshDialog);
            return AlertDialog(
              title: const Text('推理结果视频'),
              content: SizedBox(
                width: 720,
                child: _buildVideoDialogBody(refreshDialog),
              ),
              actions: [
                if (_inferVideoUrl != null)
                  TextButton(
                    onPressed: _videoLoading
                        ? null
                        : () async {
                            await _openInferVideo(_inferVideoUrl!);
                            refreshDialog();
                          },
                    child: const Text('重新加载'),
                  ),
                TextButton(
                  onPressed: () {
                    _pauseInferVideo();
                    Navigator.pop(ctx);
                  },
                  child: const Text('关闭'),
                ),
              ],
            );
          },
        );
      },
    );
    if (mounted) setState(() => _videoDialogOpen = false);
  }

  Future<void> _showZoneDialog(Map<String, dynamic>? state) async {
    final park = state?['parkAlign'] as Map<String, dynamic>?;
    final adRois = _adRois(state);
    final parkingRois = _parkingRois(state);
    final busRois = _busRois(state);
    await showDialog<void>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('区域与标定'),
        content: SizedBox(
          width: 420,
          child: SingleChildScrollView(
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  '车位: ${parkingRois.isEmpty ? "无" : "${parkingRois.length} 个"}（≥2 个可判占两车位）',
                  style: TextStyle(color: parkingRois.isEmpty ? Colors.white54 : Colors.lightGreenAccent),
                ),
                if (parkingRois.isNotEmpty) ...[
                  const SizedBox(height: 8),
                  Wrap(
                    spacing: 6,
                    runSpacing: 6,
                    children: [
                      for (final r in parkingRois)
                        InputChip(
                          label: Text('${r['name'] ?? 'slot'}'),
                          deleteIcon: const Icon(Icons.close, size: 16),
                          onDeleted: _api == null || _busy
                              ? null
                              : () async {
                                  final id = _roiId(r);
                                  if (id != null) {
                                    await _deleteAdRoi(id);
                                    if (ctx.mounted) Navigator.pop(ctx);
                                  }
                                },
                        ),
                    ],
                  ),
                ],
                const SizedBox(height: 12),
                Text(
                  '公交车位: ${busRois.isEmpty ? "无" : "${busRois.length} 个"}（区内轿车告警）',
                  style: TextStyle(color: busRois.isEmpty ? Colors.white54 : Colors.orangeAccent),
                ),
                if (busRois.isNotEmpty) ...[
                  const SizedBox(height: 8),
                  Wrap(
                    spacing: 6,
                    runSpacing: 6,
                    children: [
                      for (final r in busRois)
                        InputChip(
                          label: Text('${r['name'] ?? 'bus'}'),
                          deleteIcon: const Icon(Icons.close, size: 16),
                          onDeleted: _api == null || _busy
                              ? null
                              : () async {
                                  final id = _roiId(r);
                                  if (id != null) {
                                    await _deleteAdRoi(id);
                                    if (ctx.mounted) Navigator.pop(ctx);
                                  }
                                },
                        ),
                    ],
                  ),
                ],
                const SizedBox(height: 12),
                Text(
                  '小广告区: ${adRois.isEmpty ? "无" : "${adRois.length} 个"}',
                  style: TextStyle(color: adRois.isEmpty ? Colors.white54 : Colors.cyanAccent),
                ),
                if (adRois.isNotEmpty) ...[
                  const SizedBox(height: 8),
                  Wrap(
                    spacing: 6,
                    runSpacing: 6,
                    children: [
                      for (final r in adRois)
                        InputChip(
                          label: Text('${r['name'] ?? 'ad'}'),
                          deleteIcon: const Icon(Icons.close, size: 16),
                          onDeleted: _api == null || _busy
                              ? null
                              : () async {
                                  final id = _roiId(r);
                                  if (id != null) {
                                    await _deleteAdRoi(id);
                                    if (ctx.mounted) Navigator.pop(ctx);
                                  }
                                },
                        ),
                    ],
                  ),
                ],
                const SizedBox(height: 12),
                Text(
                  '正停标定: ${park?['ready'] == true ? "已就绪(${park?['anchors']}锚点)" : "未标定"}',
                  style: TextStyle(
                    color: park?['ready'] == true ? Colors.lightGreenAccent : Colors.white70,
                  ),
                ),
                if ((adRois.isNotEmpty || parkingRois.isNotEmpty || busRois.isNotEmpty) && _api != null) ...[
                  const SizedBox(height: 16),
                  if (parkingRois.isNotEmpty)
                    OutlinedButton.icon(
                      onPressed: _busy
                          ? null
                          : () async {
                              for (final r in parkingRois) {
                                final id = _roiId(r);
                                if (id != null) await _api!.deleteRoi(id);
                              }
                              await _api!.refreshConfig();
                              await _refresh();
                              if (ctx.mounted) Navigator.pop(ctx);
                            },
                      icon: const Icon(Icons.delete_sweep),
                      label: const Text('清空全部车位'),
                    ),
                  if (busRois.isNotEmpty) ...[
                    const SizedBox(height: 8),
                    OutlinedButton.icon(
                      onPressed: _busy
                          ? null
                          : () async {
                              for (final r in busRois) {
                                final id = _roiId(r);
                                if (id != null) await _api!.deleteRoi(id);
                              }
                              await _api!.refreshConfig();
                              await _refresh();
                              if (ctx.mounted) Navigator.pop(ctx);
                            },
                      icon: const Icon(Icons.delete_sweep),
                      label: const Text('清空全部公交位'),
                    ),
                  ],
                  if (adRois.isNotEmpty) ...[
                    const SizedBox(height: 8),
                    OutlinedButton.icon(
                      onPressed: _busy
                          ? null
                          : () async {
                              await _clearAllAdRois();
                              if (ctx.mounted) Navigator.pop(ctx);
                            },
                      icon: const Icon(Icons.delete_sweep),
                      label: const Text('清空全部小广告区'),
                    ),
                  ],
                ],
              ],
            ),
          ),
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx), child: const Text('关闭')),
        ],
      ),
    );
  }

  Future<void> _connect() async {
    setState(() {
      _error = null;
      _busy = true;
    });
    await _saveHost();
    final api = EdgeApi(_hostCtrl.text.trim());
    try {
      final state = await api.getState();
      _api = api;
      _poll?.cancel();
      _poll = Timer.periodic(const Duration(milliseconds: 400), (_) => _refresh());
      setState(() {
        _state = state;
        _busy = false;
      });
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('已连接工控机（预览图模式）')),
        );
      }
    } catch (e) {
      setState(() {
        _error = '连接失败: $e';
        _busy = false;
      });
    }
  }

  Future<void> _refresh() async {
    final api = _api;
    if (api == null) return;
    try {
      final state = await api.getState();
      final jpeg = await api.previewJpeg();
      if (!mounted) return;
      _syncCoordFromState(state);
      if (jpeg != null && !_inferAnnotated && !_videoDialogOpen) {
        await _setPreviewBytes(
          jpeg,
          coordW: (state['frameW'] as num?)?.toDouble(),
          coordH: (state['frameH'] as num?)?.toDouble(),
          annotated: false,
        );
      }
      setState(() {
        _state = state;
        _error = null;
        final liveDets = state['detections'] as Map<String, dynamic>?;
        if (liveDets != null && _detectionCount(liveDets) > 0) {
          _overlayDetections = null;
          _inferAnnotated = false;
        }
      });
    } catch (e) {
      if (mounted) setState(() => _error = '$e');
    }
  }

  Future<void> _switchCamera(int id) async {
    final api = _api;
    if (api == null) return;
    await api.selectCamera(id);
    await api.refreshConfig();
    await _refresh();
  }

  String? _hostFromRtsp(String? rtspUrl) {
    if (rtspUrl == null || rtspUrl.isEmpty) return null;
    return Uri.tryParse(rtspUrl)?.host;
  }

  Future<void> _editCameraIp() async {
    final api = _api;
    final state = _state;
    if (api == null || state == null) return;
    final cameraId = _cameraIdFromState(state);
    if (cameraId == null) {
      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('无当前摄像头')));
      return;
    }
    final cams = (state['cameras'] as List?) ?? [];
    Map<String, dynamic>? cam;
    for (final c in cams) {
      if (c is Map && (c['id'] == cameraId || (c['id'] as num?)?.toInt() == cameraId)) {
        cam = Map<String, dynamic>.from(c);
        break;
      }
    }
    final currentHost = (cam?['host'] as String?) ?? _hostFromRtsp(cam?['rtspUrl'] as String?);
    final currentPort = (cam?['port'] as num?)?.toInt() ?? 554;
    final hostCtrl = TextEditingController(text: currentHost ?? '');
    final portCtrl = TextEditingController(text: '$currentPort');
    final userCtrl = TextEditingController(text: 'admin');
    final passCtrl = TextEditingController();
    final channelCtrl = TextEditingController(text: '101');
    var changeAuth = false;

    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => StatefulBuilder(
        builder: (context, setDialogState) {
          return AlertDialog(
            title: Text('配置摄像头 IP（#${cam?['id'] ?? cameraId}）'),
            content: SizedBox(
              width: 420,
              child: SingleChildScrollView(
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      '当前: ${cam?['name'] ?? ""}  ${currentHost ?? "未配置"}',
                      style: const TextStyle(color: Colors.white70, fontSize: 12),
                    ),
                    const SizedBox(height: 12),
                    TextField(
                      controller: hostCtrl,
                      decoration: const InputDecoration(
                        labelText: '摄像头 IP / 主机名',
                        hintText: '例如 192.168.1.111',
                        border: OutlineInputBorder(),
                      ),
                      keyboardType: TextInputType.url,
                    ),
                    const SizedBox(height: 10),
                    TextField(
                      controller: portCtrl,
                      decoration: const InputDecoration(
                        labelText: '端口（默认 554）',
                        border: OutlineInputBorder(),
                      ),
                      keyboardType: TextInputType.number,
                    ),
                    const SizedBox(height: 8),
                    CheckboxListTile(
                      contentPadding: EdgeInsets.zero,
                      title: const Text('同时修改账号/通道（海康）'),
                      value: changeAuth,
                      onChanged: (v) => setDialogState(() => changeAuth = v ?? false),
                    ),
                    if (changeAuth) ...[
                      TextField(
                        controller: userCtrl,
                        decoration: const InputDecoration(
                          labelText: '用户名',
                          border: OutlineInputBorder(),
                        ),
                      ),
                      const SizedBox(height: 8),
                      TextField(
                        controller: passCtrl,
                        obscureText: true,
                        decoration: const InputDecoration(
                          labelText: '密码（留空则保留原密码）',
                          border: OutlineInputBorder(),
                        ),
                      ),
                      const SizedBox(height: 8),
                      TextField(
                        controller: channelCtrl,
                        decoration: const InputDecoration(
                          labelText: '主码流通道号（如 101）',
                          border: OutlineInputBorder(),
                        ),
                        keyboardType: TextInputType.number,
                      ),
                    ],
                    const SizedBox(height: 8),
                    const Text(
                      '保存后会写入工控机本地配置，并立即重连该路 RTSP。',
                      style: TextStyle(color: Colors.white54, fontSize: 12),
                    ),
                  ],
                ),
              ),
            ),
            actions: [
              TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('取消')),
              FilledButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('保存并重连')),
            ],
          );
        },
      ),
    );

    final host = hostCtrl.text.trim();
    final portText = portCtrl.text.trim();
    final user = userCtrl.text.trim();
    final pass = passCtrl.text;
    final channelText = channelCtrl.text.trim();
    hostCtrl.dispose();
    portCtrl.dispose();
    userCtrl.dispose();
    passCtrl.dispose();
    channelCtrl.dispose();

    if (ok != true) return;
    if (host.isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('请填写摄像头 IP')));
      return;
    }
    final port = int.tryParse(portText);
    final channel = int.tryParse(channelText);
    setState(() => _busy = true);
    try {
      final r = await api.updateCameraIp(
        cameraId: cameraId,
        host: host,
        port: port,
        username: changeAuth && user.isNotEmpty ? user : null,
        password: changeAuth && pass.isNotEmpty ? pass : null,
        channel: changeAuth ? channel : null,
      );
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('已更新摄像头地址: ${r['host']}:${r['port'] ?? 554}')),
        );
      }
      await _refresh();
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('更新失败: $e')));
      }
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  int? _cameraIdFromState(Map<String, dynamic>? state) {
    if (state == null) return null;
    final id = state['cameraId'];
    if (id is int) return id;
    if (id is num) return id.toInt();
    final cams = state['cameras'] as List?;
    if (cams != null && cams.isNotEmpty) {
      final first = cams.first as Map<String, dynamic>;
      final cid = first['id'];
      if (cid is int) return cid;
      if (cid is num) return cid.toInt();
    }
    return null;
  }

  bool _isAdRoiKind(String? kind) {
    return kind == 'ad' || kind == 'mini_ad' || kind == 'detect';
  }

  bool _isParkingRoiKind(String? kind) {
    return kind == 'parking' || kind == 'slot' || kind == 'bay';
  }

  bool _isBusRoiKind(String? kind) {
    return kind == 'bus' || kind == 'bus_slot' || kind == 'bus_parking' || kind == 'bus_bay';
  }

  bool get _isPolygonDrawMode =>
      _drawMode == DrawMode.parkingRoi || _drawMode == DrawMode.busRoi;

  List<Map<String, dynamic>> _adRois(Map<String, dynamic>? state) {
    final rois = state?['rois'] as List? ?? [];
    return rois
        .whereType<Map<String, dynamic>>()
        .where((r) => _isAdRoiKind('${r['kind'] ?? r['regionType'] ?? ''}'))
        .toList();
  }

  List<Map<String, dynamic>> _parkingRois(Map<String, dynamic>? state) {
    final rois = state?['rois'] as List? ?? [];
    return rois
        .whereType<Map<String, dynamic>>()
        .where((r) => _isParkingRoiKind('${r['kind'] ?? r['regionType'] ?? ''}'))
        .toList();
  }

  List<Map<String, dynamic>> _busRois(Map<String, dynamic>? state) {
    final rois = state?['rois'] as List? ?? [];
    return rois
        .whereType<Map<String, dynamic>>()
        .where((r) => _isBusRoiKind('${r['kind'] ?? r['regionType'] ?? ''}'))
        .toList();
  }

  int? _roiId(Map<String, dynamic> roi) {
    final id = roi['roiId'] ?? roi['id'];
    if (id is int) return id;
    if (id is num) return id.toInt();
    return null;
  }

  Future<void> _deleteAdRoi(int roiId) async {
    final api = _api;
    if (api == null) return;
    setState(() => _busy = true);
    try {
      await api.deleteRoi(roiId);
      await api.refreshConfig();
      await _refresh();
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('已删除小广告检测区')),
        );
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('删除失败: $e')),
        );
      }
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _clearAllAdRois() async {
    final api = _api;
    final adRois = _adRois(_state);
    if (api == null || adRois.isEmpty) return;
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('清空小广告检测区'),
        content: Text('确定删除当前相机的 ${adRois.length} 个小广告检测区？'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('取消')),
          FilledButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('清空')),
        ],
      ),
    );
    if (ok != true || !mounted) return;
    setState(() => _busy = true);
    try {
      for (final r in adRois) {
        final id = _roiId(r);
        if (id != null) await api.deleteRoi(id);
      }
      await api.refreshConfig();
      setState(() {
        _draftNorm.clear();
        _drawMode = DrawMode.none;
      });
      await _refresh();
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('小广告检测区已清空')),
        );
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('清空失败: $e')),
        );
      }
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  void _cancelAdRoiDraft() {
    setState(() {
      _draftNorm.clear();
      _drawMode = DrawMode.none;
    });
  }

  Future<void> _submitDraftRoi() async {
    final api = _api;
    final state = _state;
    if (api == null || state == null) return;
    final isParking = _drawMode == DrawMode.parkingRoi;
    final isBus = _drawMode == DrawMode.busRoi;
    final minPts = (isParking || isBus) ? 3 : 2;
    if (_draftNorm.length < minPts) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text(
              (isParking || isBus) ? '多边形至少点选 3 个顶点' : '请先画出区域',
            ),
          ),
        );
      }
      return;
    }
    final cameraId = _cameraIdFromState(state);
    if (cameraId == null) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('未获取到相机 ID，请点「连接」或刷新后再试')),
        );
      }
      return;
    }
    List<List<double>> polygon;
    // 广告区：两点仍按矩形；车位/公交位强制多边形点列
    if (!isParking && !isBus && _draftNorm.length == 2) {
      final a = _draftNorm[0];
      final b = _draftNorm[1];
      final x1 = a.dx < b.dx ? a.dx : b.dx;
      final y1 = a.dy < b.dy ? a.dy : b.dy;
      final x2 = a.dx < b.dx ? b.dx : a.dx;
      final y2 = a.dy < b.dy ? b.dy : a.dy;
      polygon = [
        [x1, y1],
        [x2, y1],
        [x2, y2],
        [x1, y2],
      ];
    } else {
      polygon = _draftNorm.map((p) => [p.dx, p.dy]).toList();
    }
    setState(() => _busy = true);
    try {
      if (isParking) {
        final n = _parkingRois(state).length + 1;
        await api.saveParkingRoi(cameraId: cameraId, polygon: polygon, name: 'slot_$n');
      } else if (isBus) {
        final n = _busRois(state).length + 1;
        await api.saveBusRoi(cameraId: cameraId, polygon: polygon, name: 'bus_$n');
      } else {
        await api.saveAdRoi(cameraId: cameraId, polygon: polygon);
      }
      await api.refreshConfig();
      setState(() {
        _draftNorm.clear();
        // 车位/公交位可连续画多个，广告区画完退出
        if (!isParking && !isBus) _drawMode = DrawMode.none;
      });
      await _refresh();
      if (mounted) {
        final msg = isParking
            ? '车位多边形已保存（可继续点选下一个）'
            : isBus
                ? '公交车位已保存（可继续点选下一个）'
                : '小广告检测区已保存';
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(msg)));
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('保存失败: $e')));
      }
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  void _undoDraftPoint() {
    if (_draftNorm.isEmpty) return;
    setState(() => _draftNorm.removeLast());
  }

  void _applyInferResult(Map<String, dynamic> result) {
    final b64 = result['imageBase64'] as String?;
    final dets = result['detections'] as Map<String, dynamic>?;
    final fw = (result['frameW'] as num?)?.toDouble();
    final fh = (result['frameH'] as num?)?.toDouble();
    final dfw = (result['displayFrameW'] as num?)?.toDouble();
    final dfh = (result['displayFrameH'] as num?)?.toDouble();
    final timeline = (result['timeline'] as List?)
            ?.whereType<Map<String, dynamic>>()
            .toList() ??
        const [];
    final videoUrl = result['videoUrl'] as String?;
    setState(() {
      _overlayDetections = dets;
      _videoTimeline = timeline;
      _inferVideoUrl = videoUrl;
      _state = {
        ...?_state,
        if (fw != null) 'frameW': fw,
        if (fh != null) 'frameH': fh,
        if (dfw != null) 'displayFrameW': dfw,
        if (dfh != null) 'displayFrameH': dfh,
        if (dets != null) 'detections': dets,
        if (result['parkAlign'] != null) 'parkAlign': result['parkAlign'],
      };
      if (fw != null) _coordFrameW = fw;
      if (fh != null) _coordFrameH = fh;
      if (dfw != null) _displayFrameW = dfw;
      if (dfh != null) _displayFrameH = dfh;
    });
    if (b64 != null && b64.isNotEmpty) {
      _setPreviewBytes(
        base64Decode(b64),
        coordW: fw,
        coordH: fh,
        annotated: true,
      );
    }
    if (videoUrl != null && videoUrl.isNotEmpty) {
      _openInferVideo(videoUrl).then((_) {
        if (mounted) _showVideoDialog();
      });
    }
  }

  Future<void> _inferImage() async {
    final api = _api;
    if (api == null) return;
    final pick = await FilePicker.platform.pickFiles(
      type: FileType.image,
      withData: true,
    );
    if (pick == null || pick.files.isEmpty || pick.files.first.bytes == null) return;
    setState(() {
      _busy = true;
      _inferNote = '单张图片推理中…';
    });
    try {
      final r = await api.inferImage(pick.files.first.bytes!);
      _applyInferResult(r);
      final alerts = ((r['detections'] as Map?)?['alerts'] as List?) ?? [];
      final types = alerts
          .map((a) => alertTypeLabel((a as Map)['type'] as String?))
          .toSet()
          .join('、');
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text(
              alerts.isEmpty
                  ? '图片推理完成，无告警'
                  : '图片推理完成：${alerts.length} 条告警${types.isEmpty ? "" : "（$types）"}',
            ),
          ),
        );
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('图片推理失败: $e')));
      }
    } finally {
      if (mounted) {
        setState(() {
          _busy = false;
          _inferNote = null;
        });
      }
    }
  }

  Future<void> _inferVideo() async {
    final api = _api;
    if (api == null) return;
    final pick = await FilePicker.platform.pickFiles(
      type: FileType.video,
      withData: true,
    );
    if (pick == null || pick.files.isEmpty || pick.files.first.bytes == null) return;
    final file = pick.files.first;
    setState(() {
      _busy = true;
      _inferNote = '视频推理中（工控机 NPU，请稍候）…';
    });
    try {
      final r = await api.inferVideo(
        file.bytes!,
        filename: file.name,
      );
      _applyInferResult(r);
      final processed = r['processedFrames'] ?? 0;
      final timeline = (r['timeline'] as List?) ?? [];
      final alertCount = timeline.fold<int>(
        0,
        (sum, item) => sum + (((item as Map)['alerts'] as List?)?.length ?? 0),
      );
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text(
              '视频推理完成：推理 $processed 帧，$alertCount 条告警事件；推理视频已在下方播放',
            ),
          ),
        );
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('视频推理失败: $e')));
      }
    } finally {
      if (mounted) {
        setState(() {
          _busy = false;
          _inferNote = null;
        });
      }
    }
  }

  Future<void> _calibLatest() async {
    final api = _api;
    if (api == null) return;
    setState(() => _busy = true);
    try {
      final r = await api.calibParkAlign();
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('正停标定完成：${r['anchors']} 个锚点')),
        );
      }
      await _refresh();
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('标定失败: $e')));
      }
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _calibFromFile() async {
    final api = _api;
    if (api == null) return;
    final pick = await FilePicker.platform.pickFiles(
      type: FileType.image,
      withData: true,
    );
    if (pick == null || pick.files.isEmpty || pick.files.first.bytes == null) return;
    final b64 = base64Encode(pick.files.first.bytes!);
    setState(() => _busy = true);
    try {
      final r = await api.calibParkAlign(imageBase64: b64);
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('正停标定完成：${r['anchors']} 个锚点')),
        );
      }
      await _refresh();
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('标定失败: $e')));
      }
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final state = _state;
    final dets = _effectiveDetections(state);
    final cams = (state?['cameras'] as List?) ?? [];
    final adRois = _adRois(state);
    final parkingRois = _parkingRois(state);
    final busRois = _busRois(state);
    final drawing = _drawMode != DrawMode.none;

    return Scaffold(
      appBar: AppBar(
        title: const Text('车位边缘客户端'),
        actions: [
          IconButton(
            tooltip: '配置摄像头 IP',
            onPressed: _api == null || _busy ? null : _editCameraIp,
            icon: const Icon(Icons.videocam),
          ),
          IconButton(
            tooltip: '单张图片推理',
            onPressed: _api == null || _busy ? null : _inferImage,
            icon: const Icon(Icons.image_search),
          ),
          IconButton(
            tooltip: '上传视频推理',
            onPressed: _api == null || _busy ? null : _inferVideo,
            icon: const Icon(Icons.movie),
          ),
          IconButton(
            tooltip: '清空已保存的小广告检测区',
            onPressed: _api == null || _busy || adRois.isEmpty ? null : _clearAllAdRois,
            icon: const Icon(Icons.delete_sweep),
          ),
          IconButton(
            tooltip: '画车位（多边形点选）',
            onPressed: _api == null
                ? null
                : () => setState(() {
                      _drawMode =
                          _drawMode == DrawMode.parkingRoi ? DrawMode.none : DrawMode.parkingRoi;
                      _draftNorm.clear();
                    }),
            icon: Icon(
              Icons.local_parking,
              color: _drawMode == DrawMode.parkingRoi ? Colors.lightGreenAccent : null,
            ),
          ),
          IconButton(
            tooltip: '画公交车位（区内轿车告警）',
            onPressed: _api == null
                ? null
                : () => setState(() {
                      _drawMode = _drawMode == DrawMode.busRoi ? DrawMode.none : DrawMode.busRoi;
                      _draftNorm.clear();
                    }),
            icon: Icon(
              Icons.directions_bus,
              color: _drawMode == DrawMode.busRoi ? Colors.orangeAccent : null,
            ),
          ),
          IconButton(
            tooltip: '画小广告检测区',
            onPressed: _api == null
                ? null
                : () => setState(() {
                      _drawMode = _drawMode == DrawMode.adRoi ? DrawMode.none : DrawMode.adRoi;
                      _draftNorm.clear();
                    }),
            icon: Icon(
              Icons.crop_free,
              color: _drawMode == DrawMode.adRoi ? Colors.cyanAccent : null,
            ),
          ),
        ],
      ),
      body: Column(
        children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(8, 6, 8, 4),
            child: Row(
              children: [
                Expanded(
                  child: TextField(
                    controller: _hostCtrl,
                    decoration: const InputDecoration(
                      labelText: '工控机地址',
                      hintText: 'http://chepai-rk3588:8765',
                      border: OutlineInputBorder(),
                      isDense: true,
                      contentPadding: EdgeInsets.symmetric(horizontal: 10, vertical: 8),
                    ),
                  ),
                ),
                const SizedBox(width: 8),
                FilledButton(
                  onPressed: _busy ? null : _connect,
                  child: _busy
                      ? const SizedBox(
                          width: 18,
                          height: 18,
                          child: CircularProgressIndicator(strokeWidth: 2),
                        )
                      : const Text('连接'),
                ),
              ],
            ),
          ),
          if (_inferNote != null || _error != null)
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 8),
              child: Text(
                _inferNote ?? _error ?? '',
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: TextStyle(
                  color: _error != null ? Colors.orangeAccent : Colors.lightBlueAccent,
                  fontSize: 12,
                ),
              ),
            ),
          Expanded(
            child: Stack(
              fit: StackFit.expand,
              children: [
                Builder(
                  builder: (previewCtx) {
                    Offset? tapToNorm(Offset global) {
                      final box = previewCtx.findRenderObject() as RenderBox?;
                      if (box == null || !box.hasSize) return null;
                      final local = box.globalToLocal(global);
                      return localToNormInContain(
                        local,
                        box.size,
                        _displayFrameW,
                        _displayFrameH,
                      );
                    }

                    return Stack(
                      fit: StackFit.expand,
                      children: [
                        GestureDetector(
                          behavior: HitTestBehavior.opaque,
                          onTapDown: drawing
                              ? (d) {
                                  final n = tapToNorm(d.globalPosition);
                                  if (n == null) return;
                                  setState(() => _draftNorm.add(n));
                                }
                              : null,
                          // 广告区保留拖动两点成矩形；车位/公交位只用点选
                          onPanUpdate: _drawMode == DrawMode.adRoi
                              ? (d) {
                                  final n = tapToNorm(d.globalPosition);
                                  if (n == null) return;
                                  setState(() {
                                    if (_draftNorm.isEmpty) {
                                      _draftNorm.add(n);
                                    } else if (_draftNorm.length == 1) {
                                      _draftNorm.add(n);
                                    } else {
                                      _draftNorm[_draftNorm.length - 1] = n;
                                    }
                                  });
                                }
                              : null,
                          child: Stack(
                            fit: StackFit.expand,
                            children: [
                              ColoredBox(
                                color: const Color(0xFF101820),
                                child: _previewBytes != null
                                    ? Image.memory(
                                        _previewBytes!,
                                        fit: BoxFit.contain,
                                        gaplessPlayback: true,
                                      )
                                    : const Center(
                                        child: Text(
                                          '等待工控机预览图…\n（摄像头未接电时无画面属正常）',
                                          textAlign: TextAlign.center,
                                          style: TextStyle(color: Colors.white54),
                                        ),
                                      ),
                              ),
                              CustomPaint(
                                painter: OverlayPainter(
                                  detections: dets,
                                  rois: (state?['rois'] as List?) ?? const [],
                                  coordFrameW: _coordFrameW,
                                  coordFrameH: _coordFrameH,
                                  displayFrameW: _displayFrameW,
                                  displayFrameH: _displayFrameH,
                                  skipDetections: _inferAnnotated,
                                  draftNorm: List.of(_draftNorm),
                                  drawMode: _drawMode,
                                ),
                              ),
                            ],
                          ),
                        ),
                        if (drawing)
                          Positioned(
                            left: 12,
                            bottom: 56,
                            right: 12,
                            child: Material(
                              color: Colors.black.withValues(alpha: 0.72),
                              borderRadius: BorderRadius.circular(8),
                              child: Padding(
                                padding: const EdgeInsets.symmetric(horizontal: 4, vertical: 2),
                                child: Row(
                                  children: [
                                    Expanded(
                                      child: Text(
                                        _drawMode == DrawMode.parkingRoi
                                            ? '依次点击车位顶点（≥3点）→ 保存多边形；可连续画多个'
                                            : _drawMode == DrawMode.busRoi
                                                ? '依次点击公交车位顶点（≥3点）→ 保存'
                                                : '拖动画小广告区 → 保存',
                                        style: TextStyle(
                                          color: _drawMode == DrawMode.parkingRoi
                                              ? Colors.lightGreenAccent
                                              : _drawMode == DrawMode.busRoi
                                                  ? Colors.orangeAccent
                                                  : Colors.cyanAccent,
                                          shadows: const [
                                            Shadow(blurRadius: 4, color: Colors.black),
                                          ],
                                        ),
                                      ),
                                    ),
                                    if (_isPolygonDrawMode)
                                      TextButton(
                                        onPressed: _draftNorm.isEmpty ? null : _undoDraftPoint,
                                        child: const Text('撤销点'),
                                      ),
                                    TextButton(
                                      onPressed: () => setState(() => _draftNorm.clear()),
                                      child: const Text('清空'),
                                    ),
                                    TextButton(onPressed: _cancelAdRoiDraft, child: const Text('取消')),
                                    FilledButton(
                                      onPressed: _draftNorm.length >= (_isPolygonDrawMode ? 3 : 2)
                                          ? _submitDraftRoi
                                          : null,
                                      child: Text(
                                        _drawMode == DrawMode.parkingRoi
                                            ? '保存车位'
                                            : _drawMode == DrawMode.busRoi
                                                ? '保存公交位'
                                                : '保存',
                                      ),
                                    ),
                                  ],
                                ),
                              ),
                            ),
                          ),
                      ],
                    );
                  },
                ),
                if (cams.isNotEmpty)
                  Positioned(
                    top: 8,
                    left: 8,
                    right: 8,
                    child: SingleChildScrollView(
                      scrollDirection: Axis.horizontal,
                      child: Row(
                        children: [
                          for (final c in cams)
                            Padding(
                              padding: const EdgeInsets.only(right: 6),
                              child: ChoiceChip(
                                label: Text(
                                  '${c['name'] ?? c['id']}'
                                  '${(c['host'] ?? _hostFromRtsp(c['rtspUrl'] as String?)) == null ? "" : " (${c['host'] ?? _hostFromRtsp(c['rtspUrl'] as String?)})"}',
                                ),
                                selected: c['id'] == state?['cameraId'],
                                onSelected: (_) async {
                                  final id = c['id'];
                                  final cid = id is int ? id : (id as num).toInt();
                                  await _switchCamera(cid);
                                },
                              ),
                            ),
                        ],
                      ),
                    ),
                  ),
                Positioned(
                  left: 8,
                  right: 8,
                  bottom: 8,
                  child: _floatingActionBar(dets, state, adRois, parkingRois, busRois),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }

  Widget _floatingActionBar(
    Map<String, dynamic>? dets,
    Map<String, dynamic>? state,
    List<Map<String, dynamic>> adRois,
    List<Map<String, dynamic>> parkingRois,
    List<Map<String, dynamic>> busRois,
  ) {
    final veh = (dets?['vehicles'] as List?)?.length ?? 0;
    final plate = (dets?['plates'] as List?)?.length ?? 0;
    final ad = (dets?['mini_ads'] as List?)?.length ?? 0;
    final alerts = (dets?['alerts'] as List?) ?? [];
    final alertN = _alertCount(dets);
    final typeSummary = alerts
        .map((a) => alertTypeLabel((a as Map)['type'] as String?))
        .toSet()
        .take(2)
        .join(' · ');

    return Material(
      elevation: 4,
      borderRadius: BorderRadius.circular(10),
      color: Colors.black.withValues(alpha: 0.72),
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
        child: Row(
          children: [
            Expanded(
              child: Text(
                '车$veh 牌$plate 广告$ad 告警$alertN'
                '${typeSummary.isEmpty ? "" : " [$typeSummary]"}',
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: const TextStyle(fontSize: 12, color: Colors.white70),
              ),
            ),
            TextButton.icon(
              onPressed: () => _showZoneDialog(state),
              icon: Badge(
                isLabelVisible: adRois.isNotEmpty || parkingRois.isNotEmpty || busRois.isNotEmpty,
                label: Text('${adRois.length + parkingRois.length + busRois.length}'),
                child: const Icon(Icons.crop_free, size: 18),
              ),
              label: const Text('区域'),
            ),
            TextButton.icon(
              onPressed: (alertN > 0 || _videoTimeline.isNotEmpty)
                  ? () => _showAlertsDialog(dets)
                  : null,
              icon: Badge(
                isLabelVisible: alertN > 0,
                label: Text('$alertN'),
                child: const Icon(Icons.warning_amber_rounded, size: 18),
              ),
              label: const Text('告警'),
            ),
            if (_inferVideoUrl != null)
              TextButton.icon(
                onPressed: _showVideoDialog,
                icon: Icon(
                  _videoLoading ? Icons.hourglass_top : Icons.play_circle_outline,
                  size: 18,
                ),
                label: const Text('视频'),
              ),
          ],
        ),
      ),
    );
  }

  Widget _buildVideoDialogBody(VoidCallback onChanged) {
    final controller = _videoController;
    final ready = controller != null && controller.value.isInitialized;
    if (_videoLoading) {
      return const Padding(
        padding: EdgeInsets.symmetric(vertical: 48),
        child: Center(child: CircularProgressIndicator()),
      );
    }
    if (_videoError != null) {
      return Padding(
        padding: const EdgeInsets.symmetric(vertical: 24),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Text('加载失败: $_videoError', style: const TextStyle(color: Colors.orangeAccent)),
            const SizedBox(height: 12),
            FilledButton.icon(
              onPressed: _inferVideoUrl == null
                  ? null
                  : () async {
                      await _openInferVideo(_inferVideoUrl!);
                      onChanged();
                    },
              icon: const Icon(Icons.refresh),
              label: const Text('重试'),
            ),
          ],
        ),
      );
    }
    if (!ready) {
      return const Padding(
        padding: EdgeInsets.symmetric(vertical: 24),
        child: Text('视频尚未就绪', style: TextStyle(color: Colors.white54)),
      );
    }
    return Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        AspectRatio(
          aspectRatio: controller.value.aspectRatio > 0 ? controller.value.aspectRatio : 16 / 9,
          child: Stack(
            alignment: Alignment.center,
            children: [
              VideoPlayer(controller),
              if (!controller.value.isPlaying)
                IconButton.filled(
                  iconSize: 56,
                  onPressed: () {
                    controller.play();
                    onChanged();
                  },
                  icon: const Icon(Icons.play_arrow),
                ),
            ],
          ),
        ),
        VideoProgressIndicator(
          controller,
          allowScrubbing: true,
          colors: const VideoProgressColors(
            playedColor: Colors.lightBlueAccent,
            bufferedColor: Colors.white24,
            backgroundColor: Colors.white10,
          ),
        ),
        Row(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            IconButton(
              tooltip: controller.value.isPlaying ? '暂停' : '播放',
              onPressed: () {
                if (controller.value.isPlaying) {
                  controller.pause();
                } else {
                  controller.play();
                }
                onChanged();
              },
              icon: Icon(controller.value.isPlaying ? Icons.pause : Icons.play_arrow),
            ),
          ],
        ),
      ],
    );
  }

  Widget _buildAlertsContent(Map<String, dynamic>? dets) {
    final alerts = (dets?['alerts'] as List?)?.whereType<Map<String, dynamic>>().toList() ?? [];
    final hasTimeline = _videoTimeline.isNotEmpty;
    if (alerts.isEmpty && !hasTimeline) {
      return const Center(child: Text('暂无告警', style: TextStyle(color: Colors.white54)));
    }
    return ListView(
      children: [
        if (alerts.isNotEmpty) ...[
          const Text('当前帧', style: TextStyle(color: Colors.white54, fontSize: 12)),
          const SizedBox(height: 4),
          for (final a in alerts) _alertTile(a),
        ],
        if (hasTimeline) ...[
          const SizedBox(height: 12),
          const Text('视频时间线', style: TextStyle(color: Colors.white54, fontSize: 12)),
          const SizedBox(height: 4),
          for (final item in _videoTimeline) _timelineTile(item),
        ],
      ],
    );
  }

  Widget _alertTile(Map<String, dynamic> alert) {
    final type = alert['type'] as String?;
    final score = (alert['score'] as num?)?.toDouble();
    final raw = alert['raw'] as Map<String, dynamic>?;
    final reason = raw?['reason'] as String?;
    return ListTile(
      dense: true,
      contentPadding: EdgeInsets.zero,
      leading: CircleAvatar(
        radius: 14,
        backgroundColor: alertTypeColor(type).withValues(alpha: 0.25),
        child: Icon(Icons.warning_amber_rounded, size: 16, color: alertTypeColor(type)),
      ),
      title: Text(
        alertTypeLabel(type),
        style: TextStyle(color: alertTypeColor(type), fontWeight: FontWeight.w600),
      ),
      subtitle: Text(
        [
          if (score != null) '置信度 ${score.toStringAsFixed(2)}',
          if (reason != null && reason.isNotEmpty) reason,
        ].join(' · '),
        style: const TextStyle(color: Colors.white54, fontSize: 12),
      ),
    );
  }

  Widget _timelineTile(Map<String, dynamic> item) {
    final frame = item['frame'];
    final timeSec = item['timeSec'];
    final alerts = (item['alerts'] as List?)?.whereType<Map<String, dynamic>>().toList() ?? [];
    final labels = alerts.map((a) => alertTypeLabel(a['type'] as String?)).join('、');
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 2),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SizedBox(
            width: 88,
            child: Text(
              '帧 $frame\n${timeSec}s',
              style: const TextStyle(color: Colors.white54, fontSize: 12),
            ),
          ),
          Expanded(
            child: Wrap(
              spacing: 6,
              runSpacing: 4,
              children: [
                for (final a in alerts)
                  Chip(
                    label: Text(
                      '${alertTypeLabel(a['type'] as String?)} ${((a['score'] as num?) ?? 0).toStringAsFixed(2)}',
                      style: TextStyle(color: alertTypeColor(a['type'] as String?), fontSize: 12),
                    ),
                    backgroundColor: alertTypeColor(a['type'] as String?).withValues(alpha: 0.15),
                    side: BorderSide(color: alertTypeColor(a['type'] as String?).withValues(alpha: 0.4)),
                    visualDensity: VisualDensity.compact,
                    padding: EdgeInsets.zero,
                  ),
                if (labels.isEmpty) const Text('—', style: TextStyle(color: Colors.white38)),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class OverlayPainter extends CustomPainter {
  OverlayPainter({
    required this.detections,
    required this.rois,
    required this.coordFrameW,
    required this.coordFrameH,
    required this.displayFrameW,
    required this.displayFrameH,
    required this.skipDetections,
    required this.draftNorm,
    required this.drawMode,
  });

  final Map<String, dynamic>? detections;
  final List rois;
  final double coordFrameW;
  final double coordFrameH;
  final double displayFrameW;
  final double displayFrameH;
  final bool skipDetections;
  final List<Offset> draftNorm;
  final DrawMode drawMode;

  @override
  void paint(Canvas canvas, Size size) {
    final layout = previewContainLayout(size, displayFrameW, displayFrameH);
    final scale = layout.scale;
    final ox = layout.ox;
    final oy = layout.oy;
    final sx = displayFrameW / coordFrameW;
    final sy = displayFrameH / coordFrameH;

    Offset mapPx(num x, num y) => Offset(ox + x * sx * scale, oy + y * sy * scale);
    Offset mapNorm(Offset n) => Offset(
          ox + n.dx * layout.dw,
          oy + n.dy * layout.dh,
        );

    for (final r in rois) {
      final m = r as Map<String, dynamic>;
      final kind = '${m['kind'] ?? m['regionType'] ?? ''}';
      Color color;
      if (kind == 'parking' || kind == 'slot' || kind == 'bay') {
        color = const Color(0xFF00C800);
      } else if (kind == 'bus' || kind == 'bus_slot' || kind == 'bus_parking' || kind == 'bus_bay') {
        color = const Color(0xFFFF8C00);
      } else if (kind == 'ad' || kind == 'mini_ad' || kind == 'detect') {
        color = const Color(0xFF00DCED);
      } else {
        continue;
      }
      final poly = (m['polygon'] as List?) ?? [];
      if (poly.length < 2) continue;
      final path = Path();
      for (var i = 0; i < poly.length; i++) {
        final p = poly[i] as List;
        final nx = (p[0] as num).toDouble();
        final ny = (p[1] as num).toDouble();
        final pt = mapPx(nx * coordFrameW, ny * coordFrameH);
        if (i == 0) {
          path.moveTo(pt.dx, pt.dy);
        } else {
          path.lineTo(pt.dx, pt.dy);
        }
      }
      path.close();
      canvas.drawPath(
        path,
        Paint()
          ..style = PaintingStyle.stroke
          ..strokeWidth = 2
          ..color = color,
      );
      final label = '${m['name'] ?? kind}';
      final tp = TextPainter(
        text: TextSpan(
          text: label,
          style: TextStyle(color: color, fontSize: 11, shadows: const [
            Shadow(blurRadius: 3, color: Colors.black),
          ]),
        ),
        textDirection: ui.TextDirection.ltr,
      )..layout();
      final bounds = path.getBounds();
      tp.paint(canvas, Offset(bounds.left, (bounds.top - 14).clamp(0, size.height)));
    }

    void drawBox(List xyxy, Color color, String label) {
      if (xyxy.length < 4) return;
      final r = Rect.fromPoints(
        mapPx(xyxy[0] as num, xyxy[1] as num),
        mapPx(xyxy[2] as num, xyxy[3] as num),
      );
      canvas.drawRect(
        r,
        Paint()
          ..style = PaintingStyle.stroke
          ..strokeWidth = 2
          ..color = color,
      );
      final tp = TextPainter(
        text: TextSpan(
          text: label,
          style: TextStyle(color: color, fontSize: 12, shadows: const [
            Shadow(blurRadius: 3, color: Colors.black),
          ]),
        ),
        textDirection: ui.TextDirection.ltr,
      )..layout();
      tp.paint(canvas, Offset(r.left, (r.top - 14).clamp(0, size.height)));
    }

    final dets = detections;
    if (dets != null && !skipDetections) {
      for (final v in (dets['vehicles'] as List?) ?? []) {
        final m = v as Map<String, dynamic>;
        drawBox(
          m['xyxy'] as List,
          const Color(0xFFFFB400),
          '${m['class'] ?? 'veh'} ${(m['conf'] as num?)?.toStringAsFixed(2) ?? ''}',
        );
      }
      for (final p in (dets['plates'] as List?) ?? []) {
        final m = p as Map<String, dynamic>;
        drawBox(
          m['xyxy'] as List,
          const Color(0xFFFF00FF),
          '${m['class'] ?? 'plate'} ${(m['conf'] as num?)?.toStringAsFixed(2) ?? ''}',
        );
      }
      for (final a in (dets['mini_ads'] as List?) ?? []) {
        final m = a as Map<String, dynamic>;
        drawBox(m['xyxy'] as List, const Color(0xFF4080FF), 'ad ${(m['conf'] as num?)?.toStringAsFixed(2) ?? ''}');
      }
      for (final al in (dets['alerts'] as List?) ?? []) {
        final m = al as Map<String, dynamic>;
        final raw = m['raw'] as Map<String, dynamic>?;
        final bbox = raw?['bbox'] ?? raw?['bbox_vehicle'];
        if (bbox is List) {
          drawBox(bbox, const Color(0xFFFF2020), alertTypeLabel(m['type'] as String?));
        }
      }
      for (final al in (dets['align'] as List?) ?? []) {
        final m = al as Map<String, dynamic>;
        final bbox = m['bbox'] as List?;
        final pb = m['plate_bbox'] as List?;
        if (bbox == null || pb == null || bbox.length < 4 || pb.length < 4) continue;
        final vc = mapPx((bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2);
        final pc = mapPx((pb[0] + pb[2]) / 2, (pb[1] + pb[3]) / 2);
        final bad = ((m['ddx'] as num?) ?? 0) > ((m['dx_threshold'] as num?) ?? 0.15);
        final c = bad ? const Color(0xFFFF2020) : const Color(0xFFFFFF00);
        canvas.drawLine(vc, pc, Paint()..color = c..strokeWidth = 2);
        canvas.drawCircle(vc, 3, Paint()..color = c);
        canvas.drawCircle(pc, 3, Paint()..color = c);
      }
    }

    if (draftNorm.isNotEmpty) {
      final draftColor = drawMode == DrawMode.parkingRoi
          ? Colors.lightGreenAccent
          : drawMode == DrawMode.busRoi
              ? Colors.orangeAccent
              : Colors.cyanAccent;
      final paint = Paint()
        ..color = draftColor
        ..strokeWidth = 2
        ..style = PaintingStyle.stroke;
      if (drawMode == DrawMode.parkingRoi || drawMode == DrawMode.busRoi) {
        // 车位/公交位：始终按折线/多边形点选预览
        for (final p in draftNorm) {
          canvas.drawCircle(mapNorm(p), 4, Paint()..color = draftColor..style = PaintingStyle.fill);
        }
        if (draftNorm.length >= 2) {
          final path = Path()..moveTo(mapNorm(draftNorm.first).dx, mapNorm(draftNorm.first).dy);
          for (var i = 1; i < draftNorm.length; i++) {
            final p = mapNorm(draftNorm[i]);
            path.lineTo(p.dx, p.dy);
          }
          if (draftNorm.length >= 3) path.close();
          canvas.drawPath(path, paint);
        }
      } else if (draftNorm.length == 1) {
        canvas.drawCircle(mapNorm(draftNorm.first), 4, paint..style = PaintingStyle.fill);
      } else if (draftNorm.length == 2) {
        final a = mapNorm(draftNorm[0]);
        final b = mapNorm(draftNorm[1]);
        canvas.drawRect(Rect.fromPoints(a, b), paint);
      } else {
        final path = Path()..moveTo(mapNorm(draftNorm.first).dx, mapNorm(draftNorm.first).dy);
        for (var i = 1; i < draftNorm.length; i++) {
          final p = mapNorm(draftNorm[i]);
          path.lineTo(p.dx, p.dy);
        }
        path.close();
        canvas.drawPath(path, paint);
      }
    }
  }

  @override
  bool shouldRepaint(covariant OverlayPainter oldDelegate) => true;
}
