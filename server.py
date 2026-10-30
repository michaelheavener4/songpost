"""SONGPOST's local, file-backed HTTP API. Run with python3 server.py."""
import hashlib
import html
import json
import os
from pathlib import Path
import re
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

import engine

BASE = Path(__file__).resolve().parent
DATA = BASE / 'data'
LOCK = threading.RLock()
SLUG = r'[0-9a-f]{8}'


def utc():
    return datetime.now(timezone.utc).isoformat()


def stats():
    """Always derive public counters directly from the current files."""
    songs = DATA / 'songs'
    result = {'songs': sum(p.is_dir() for p in songs.iterdir()) if songs.exists() else 0}
    for name in ('plays', 'feedback'):
        path = DATA / (name + '.log')
        with path.open(encoding='utf-8') if path.exists() else open(os.devnull) as log:
            result[name] = sum(1 for _ in log)
    return result


def save_meta(folder, meta):
    """Replace metadata atomically so readers never see a partial JSON document."""
    temporary = folder / 'meta.tmp'
    temporary.write_text(json.dumps(meta, indent=2), encoding='utf-8')
    temporary.replace(folder / 'meta.json')


def append_log(name, record):
    DATA.mkdir(parents=True, exist_ok=True)
    with (DATA / (name + '.log')).open('a', encoding='utf-8') as log:
        log.write(json.dumps(dict(at=utc(), **record)) + '\n')


class Handler(BaseHTTPRequestHandler):
    def send(self, status, body, content_type):
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.end_headers()
        self.wfile.write(body)

    def json(self, status, value):
        self.send(status, json.dumps(value).encode(), 'application/json; charset=utf-8')

    def meta(self, slug):
        if not isinstance(slug, str) or not re.fullmatch(SLUG, slug):
            raise ValueError('Invalid song slug')
        path = DATA / 'songs' / slug / 'meta.json'
        if not path.is_file():
            raise FileNotFoundError('Song not found')
        return json.loads(path.read_text(encoding='utf-8'))

    def do_GET(self):
        path = urlsplit(self.path).path
        try:
            if path == '/':
                self.send(200, (BASE / 'index.html').read_bytes(), 'text/html; charset=utf-8')
            elif path == '/api/stats':
                with LOCK:
                    self.json(200, stats())
            elif match := re.fullmatch(r'/s/(' + SLUG + r')', path):
                with LOCK:
                    meta = self.meta(match[1])
                slug = meta['slug']
                versions = ''.join(
                    '<li>Version {}: {} <a href="/songs/{}/{}">Listen</a></li>'.format(
                        v['n'], html.escape(v['feedback'] or 'original'), slug, v['file'])
                    for v in meta['versions'])
                replacements = {'TITLE': html.escape(meta['versions'][-1]['title']),
                                'PROMPT': html.escape(meta['prompt']), 'SLUG': slug,
                                'AUDIO_SRC': '/songs/' + slug + '/' + meta['versions'][-1]['file'],
                                'VERSIONS': versions}
                template = (BASE / 'song_template.html').read_text(encoding='utf-8')
                # One pass avoids interpreting placeholder-like text from user input.
                page = re.sub(r'\{\{(TITLE|PROMPT|SLUG|AUDIO_SRC|VERSIONS)\}\}',
                              lambda m: replacements[m[1]], template)
                self.send(200, page.encode(), 'text/html; charset=utf-8')
            elif match := re.fullmatch(r'/songs/(' + SLUG + r')/(v[1-9][0-9]*\.wav)', path):
                self.send(200, (DATA / 'songs' / match[1] / match[2]).read_bytes(), 'audio/wav')
            else:
                self.json(404, {'error': 'Not found'})
        except FileNotFoundError:
            self.json(404, {'error': 'Song or audio not found'})
        except (OSError, ValueError):
            self.json(500, {'error': 'Could not read song data'})

    def do_POST(self):
        path = urlsplit(self.path).path
        if path not in ('/api/generate', '/api/feedback', '/api/play'):
            self.json(404, {'error': 'Not found'})
            return
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= 16384:
                raise ValueError('JSON body must be between 1 and 16384 bytes')
            body = json.loads(self.rfile.read(length))
            if not isinstance(body, dict):
                raise ValueError('Expected a JSON object')
            field = 'prompt' if path == '/api/generate' else 'text' if path == '/api/feedback' else 'slug'
            if not isinstance(body.get(field), str) or not body[field].strip():
                raise ValueError(field + ' must be a nonempty string')
            if len(body[field]) > 4000:
                raise ValueError(field + ' is too long')
            if path == '/api/generate':
                prompt = body['prompt']
                audio, info = engine.generate(prompt)
                with LOCK:
                    songs = DATA / 'songs'
                    songs.mkdir(parents=True, exist_ok=True)
                    while True:
                        slug = hashlib.sha256((prompt + str(time.time_ns())).encode()).hexdigest()[:8]
                        folder = songs / slug
                        try:
                            folder.mkdir()
                            break
                        except FileExistsError:
                            continue
                    (folder / 'v1.wav').write_bytes(audio)
                    save_meta(folder, {'slug': slug, 'prompt': prompt, 'created_utc': utc(),
                                      'versions': [dict(n=1, file='v1.wav', feedback=None,
                                                        params=info, title=info['title'])]})
                self.json(200, dict(slug=slug, url='/s/' + slug, title=info['title']))
            else:
                # Serialize version assignment and logs across concurrent requests.
                with LOCK:
                    meta = self.meta(body.get('slug'))
                    slug = meta['slug']
                    if path == '/api/play':
                        append_log('plays', {'slug': slug})
                        self.json(200, {'ok': True})
                    else:
                        audio, info = engine.generate(meta['prompt'], feedback=body['text'],
                                                      parent=meta['versions'][-1]['params'])
                        n = meta['versions'][-1]['n'] + 1
                        filename = 'v' + str(n) + '.wav'
                        folder = DATA / 'songs' / slug
                        (folder / filename).write_bytes(audio)
                        meta['versions'].append(dict(n=n, file=filename, feedback=body['text'],
                                                     params=info, title=info['title']))
                        save_meta(folder, meta)
                        append_log('feedback', dict(slug=slug, text=body['text'], n=n))
                        self.json(200, dict(n=n, version=n, audio_url='/songs/' + slug + '/' + filename))
        except (ValueError, UnicodeDecodeError) as exc:
            self.json(400, {'error': str(exc)})
        except FileNotFoundError:
            self.json(404, {'error': 'Song not found'})
        except OSError:
            self.json(500, {'error': 'Could not save song data'})


if __name__ == '__main__':
    port = int(os.environ.get('PORT', '8377'))
    server = ThreadingHTTPServer(('', port), Handler)
    print('SONGPOST listening on http://localhost:' + str(port), flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
