import 'dart:convert';
import 'dart:io';
import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;
import 'package:shared_preferences/shared_preferences.dart';
import 'package:record/record.dart';
import 'package:audioplayers/audioplayers.dart';
import 'package:path_provider/path_provider.dart';

void main() => runApp(const AselApp());

class AselApp extends StatelessWidget {
  const AselApp({super.key});
  @override
  Widget build(BuildContext context) => MaterialApp(
    title: 'ASEL',
    debugShowCheckedModeBanner: false,
    theme: ThemeData(
      brightness: Brightness.dark,
      colorScheme: ColorScheme.fromSeed(seedColor: const Color(0xffbb78d1), brightness: Brightness.dark),
      scaffoldBackgroundColor: const Color(0xff111018),
      useMaterial3: true,
    ),
    home: const ChatPage(),
  );
}

class ChatMessage {
  final String text;
  final bool fromUser;
  ChatMessage(this.text, this.fromUser);
}

class ChatPage extends StatefulWidget {
  const ChatPage({super.key});
  @override
  State<ChatPage> createState() => _ChatPageState();
}

class _ChatPageState extends State<ChatPage> {
  final _controller = TextEditingController();
  final _scroll = ScrollController();
  final _recorder = AudioRecorder();
  final _player = AudioPlayer();
  bool _recording = false;
  final List<ChatMessage> _messages = [
    ChatMessage('Сәлем! Я Асель 💫 Чем займёмся?', false),
  ];
  bool _sending = false;
  String _baseUrl = 'https://YOUR_SERVER_DOMAIN';
  String _secret = '';
  String _userId = 'mobile-owner';

  @override
  void initState() {
    super.initState();
    _loadSettings();
  }

  Future<void> _loadSettings() async {
    final p = await SharedPreferences.getInstance();
    setState(() {
      _baseUrl = p.getString('baseUrl') ?? _baseUrl;
      _secret = p.getString('secret') ?? '';
      _userId = p.getString('userId') ?? 'mobile-owner';
    });
  }

  Future<void> _settings() async {
    final url = TextEditingController(text: _baseUrl);
    final key = TextEditingController(text: _secret);
    final user = TextEditingController(text: _userId);
    await showDialog<void>(context: context, builder: (ctx) => AlertDialog(
      title: const Text('Подключение к ASEL'),
      content: Column(mainAxisSize: MainAxisSize.min, children: [
        TextField(controller: url, decoration: const InputDecoration(labelText: 'Адрес сервера')),
        TextField(controller: key, obscureText: true, decoration: const InputDecoration(labelText: 'Ключ доступа')),
        TextField(controller: user, decoration: const InputDecoration(labelText: 'ID пользователя (для связи Telegram)')),
      ]),
      actions: [
        TextButton(onPressed: () => Navigator.pop(ctx), child: const Text('Отмена')),
        TextButton(onPressed: () async {
          final codeCtrl = TextEditingController();
          final code = await showDialog<String>(context: ctx, builder: (dctx) => AlertDialog(
            title: const Text('Связать с Telegram'),
            content: TextField(controller: codeCtrl, keyboardType: TextInputType.number,
              decoration: const InputDecoration(labelText: 'Код из команды /link')),
            actions: [
              TextButton(onPressed: () => Navigator.pop(dctx), child: const Text('Отмена')),
              FilledButton(onPressed: () => Navigator.pop(dctx, codeCtrl.text.trim()), child: const Text('Связать')),
            ],
          ));
          if (code == null || code.isEmpty) return;
          try {
            final uri = Uri.parse('${url.text.trim().replaceAll(RegExp(r'/$'), '')}/api/link');
            final res = await http.post(uri, headers: {'Content-Type':'application/json','X-Asel-Secret':key.text.trim()},
              body: jsonEncode({'mobile_user_id':user.text.trim(),'code':code})).timeout(const Duration(seconds: 20));
            if (res.statusCode != 200) throw Exception(res.body);
            if (ctx.mounted) ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Telegram и приложение связаны')));
          } catch (e) {
            if (ctx.mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('Не удалось связать: $e')));
          }
        }, child: const Text('Связать Telegram')),
        FilledButton(onPressed: () async {
          final p = await SharedPreferences.getInstance();
          await p.setString('baseUrl', url.text.trim());
          await p.setString('secret', key.text.trim());
          await p.setString('userId', user.text.trim());
          setState(() { _baseUrl = url.text.trim(); _secret = key.text.trim(); _userId = user.text.trim(); });
          if (ctx.mounted) Navigator.pop(ctx);
        }, child: const Text('Сохранить')),
      ],
    ));
  }

  Future<void> _send() async {
    final text = _controller.text.trim();
    if (text.isEmpty || _sending) return;
    _controller.clear();
    setState(() { _messages.add(ChatMessage(text, true)); _sending = true; });
    try {
      final uri = Uri.parse('${_baseUrl.replaceAll(RegExp(r'/$'), '')}/api/chat');
      final response = await http.post(uri,
        headers: {'Content-Type': 'application/json', 'X-Asel-Secret': _secret},
        body: jsonEncode({'user_id': _userId, 'message': text}),
      ).timeout(const Duration(seconds: 60));
      if (response.statusCode != 200) {
        throw Exception('Сервер ответил ${response.statusCode}: ${response.body}');
      }
      final data = jsonDecode(response.body) as Map<String, dynamic>;
      setState(() => _messages.add(ChatMessage(data['reply']?.toString() ?? 'Пустой ответ', false)));
    } catch (e) {
      setState(() => _messages.add(ChatMessage('Не удалось связаться с сервером. Проверь адрес, ключ и подключение. ($e)', false)));
    } finally {
      setState(() => _sending = false);
      if (_scroll.hasClients) _scroll.animateTo(_scroll.position.maxScrollExtent,
        duration: const Duration(milliseconds: 250), curve: Curves.easeOut);
    }
  }

  Future<void> _toggleRecording() async {
    if (_sending) return;
    try {
      if (!_recording) {
        final permitted = await _recorder.hasPermission();
        if (!permitted) {
          setState(() => _messages.add(ChatMessage('Нужно разрешить доступ к микрофону.', false)));
          return;
        }
        final dir = await getTemporaryDirectory();
        final path = '${dir.path}/asel_voice_${DateTime.now().millisecondsSinceEpoch}.wav';
        await _recorder.start(
          const RecordConfig(
            encoder: AudioEncoder.wav,
            sampleRate: 16000,
            numChannels: 1,
          ),
          path: path,
        );
        setState(() => _recording = true);
      } else {
        final path = await _recorder.stop();
        setState(() { _recording = false; _sending = true; });
        if (path == null) throw Exception('Не удалось сохранить запись');
        await _sendVoice(path);
      }
    } catch (e) {
      setState(() {
        _recording = false;
        _sending = false;
        _messages.add(ChatMessage('Не получилось записать голос: $e', false));
      });
    }
  }

  Future<void> _sendVoice(String path) async {
    try {
      final uri = Uri.parse('${_baseUrl.replaceAll(RegExp(r'/$'), '')}/api/voice');
      final request = http.MultipartRequest('POST', uri)
        ..headers['X-Asel-Secret'] = _secret
        ..fields['user_id'] = _userId
        ..files.add(await http.MultipartFile.fromPath('file', path, filename: 'voice.wav'));
      final streamed = await request.send().timeout(const Duration(seconds: 120));
      final response = await http.Response.fromStream(streamed);
      if (response.statusCode != 200) {
        throw Exception('Сервер ответил ${response.statusCode}: ${response.body}');
      }
      final data = jsonDecode(response.body) as Map<String, dynamic>;
      final transcript = data['transcript']?.toString() ?? '';
      final reply = data['reply']?.toString() ?? 'Пустой ответ';
      setState(() {
        if (transcript.isNotEmpty) _messages.add(ChatMessage('🎙 $transcript', true));
        _messages.add(ChatMessage(reply, false));
      });
      final encoded = data['audio_base64']?.toString();
      if (encoded != null && encoded.isNotEmpty) {
        final bytes = base64Decode(encoded);
        final dir = await getTemporaryDirectory();
        final audioPath = '${dir.path}/asel_reply.mp3';
        final audioFile = File(audioPath);
        await audioFile.writeAsBytes(bytes, flush: true);
        await _player.play(DeviceFileSource(audioPath));
      }
    } catch (e) {
      setState(() => _messages.add(ChatMessage('Не удалось обработать голос. Проверь сервер, ключ и настройки аудио. ($e)', false)));
    } finally {
      setState(() => _sending = false);
    }
  }

  @override
  void dispose() {
    _controller.dispose();
    _scroll.dispose();
    _recorder.dispose();
    _player.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(
      title: const Row(children: [
        CircleAvatar(
          radius: 22,
          backgroundColor: Color(0xff252330),
          backgroundImage: AssetImage('assets/avatars/asel_primary_black_hoodie.webp'),
        ),
        SizedBox(width: 10),
        Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text('ASEL', style: TextStyle(fontWeight: FontWeight.bold)),
          Text('Персональная помощница', style: TextStyle(fontSize: 11, color: Colors.white60)),
        ])
      ]),
      actions: [IconButton(onPressed: _settings, icon: const Icon(Icons.settings_outlined))],
    ),
    body: Column(children: [
      Expanded(child: ListView.builder(
        controller: _scroll, padding: const EdgeInsets.all(16),
        itemCount: _messages.length + (_sending ? 1 : 0),
        itemBuilder: (context, i) {
          if (_sending && i == _messages.length) {
            return const Align(alignment: Alignment.centerLeft, child: Padding(
              padding: EdgeInsets.all(8), child: Text('Асель печатает…', style: TextStyle(color: Colors.white54))));
          }
          final m = _messages[i];
          final bubble = Container(
            constraints: const BoxConstraints(maxWidth: 320),
            margin: const EdgeInsets.only(bottom: 12),
            padding: const EdgeInsets.symmetric(horizontal: 15, vertical: 12),
            decoration: BoxDecoration(
              color: m.fromUser ? const Color(0xff70427f) : const Color(0xff252330),
              borderRadius: BorderRadius.circular(18),
            ),
            child: Text(m.text, style: const TextStyle(fontSize: 15, height: 1.35)),
          );
          if (m.fromUser) {
            return Align(alignment: Alignment.centerRight, child: bubble);
          }
          return Align(
            alignment: Alignment.centerLeft,
            child: Row(crossAxisAlignment: CrossAxisAlignment.end, children: [
              const CircleAvatar(
                radius: 13,
                backgroundImage: AssetImage('assets/avatars/asel_primary_black_hoodie.webp'),
              ),
              const SizedBox(width: 7),
              Flexible(child: bubble),
            ]),
          );
        },
      )),
      SafeArea(child: Padding(
        padding: const EdgeInsets.fromLTRB(12, 8, 12, 12),
        child: Row(children: [
          Expanded(child: TextField(
            controller: _controller, minLines: 1, maxLines: 5,
            textInputAction: TextInputAction.send, onSubmitted: (_) => _send(),
            decoration: InputDecoration(
              hintText: 'Напиши Асель…', filled: true, fillColor: const Color(0xff252330),
              border: OutlineInputBorder(borderRadius: BorderRadius.circular(24), borderSide: BorderSide.none),
              contentPadding: const EdgeInsets.symmetric(horizontal: 18, vertical: 12),
            ),
          )),
          const SizedBox(width: 8),
          IconButton(
            tooltip: _recording ? 'Остановить запись' : 'Голосовое сообщение',
            onPressed: _sending ? null : _toggleRecording,
            icon: Icon(_recording ? Icons.stop_circle_outlined : Icons.mic_none),
            color: _recording ? Colors.redAccent : null,
          ),
          IconButton.filled(onPressed: _sending || _recording ? null : _send, icon: const Icon(Icons.arrow_upward)),
        ]),
      )),
    ]),
  );
}
