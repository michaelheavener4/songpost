"""Deterministic, sample-free eight-bar music synthesis using only Python."""
import array
import hashlib
import io
import math
import random
import re
import sys
import wave

RATE = 22050
TAU = 2 * math.pi


def generate(prompt: str, feedback: str | None = None,
             parent: dict | None = None) -> tuple[bytes, dict]:
    """Render a song, preserving the full feedback chain in returned params."""
    digest = hashlib.sha256(prompt.encode()).digest()
    rng = random.Random(int.from_bytes(digest, 'big'))
    words = prompt.lower()
    params = {
        'root': rng.randint(45, 57),
        'mode': 'minor' if any(w in words for w in ('dark', 'haunt', 'sad', 'rain', 'lonely')) else 'major',
        'tempo': rng.randint(84, 128),
        'progression': rng.choice([[0, 3, 4, 0], [0, 5, 3, 4], [0, 2, 5, 3]]),
        'drum_density': rng.uniform(.35, .8),
        'bass_weight': rng.uniform(.6, 1.1),
        'brightness': rng.uniform(.2, .8),
        'melody_density': rng.uniform(.5, .85),
        'feedback_chain': [],
    }
    if any(w in words for w in ('disco', 'dance', 'rock', 'fast')):
        params.update(tempo=124, drum_density=.9)
    if any(w in words for w in ('ambient', 'slow', 'sleep')):
        params.update(tempo=84, drum_density=.25)
    if any(w in words for w in ('bright', 'sun', 'happy')):
        params.update(mode='major', brightness=.85)
    if parent is not None:
        source = parent.get('params', parent)
        params.update({k: source[k] for k in params if k in source})
    params['feedback_chain'] = list(params['feedback_chain'])
    if feedback is not None:
        params['feedback_chain'].append(feedback)
        f = feedback.lower()
        if 'darker' in f:
            params.update(mode='minor', root=params['root'] - 2,
                          tempo=params['tempo'] - 6, brightness=params['brightness'] - .2)
        if 'brighter' in f:
            params.update(mode='major', root=params['root'] + 2,
                          tempo=params['tempo'] + 4, brightness=params['brightness'] + .2)
        for phrase, field, delta in [('more drums', 'drum_density', .25),
                                     ('less drums', 'drum_density', -.25),
                                     ('faster', 'tempo', 8), ('slower', 'tempo', -8),
                                     ('more bass', 'bass_weight', .3),
                                     ('more melody', 'melody_density', .2)]:
            if phrase in f:
                params[field] += delta
    for field, low, high in [('root', 45, 57), ('tempo', 84, 128),
                             ('drum_density', 0, 1), ('bass_weight', .1, 2),
                             ('brightness', 0, 1), ('melody_density', .1, 1)]:
        params[field] = max(low, min(high, params[field]))
    # Length-prefix each string to avoid ambiguous prompt/feedback concatenations.
    parts = [prompt] + params['feedback_chain']
    seed = hashlib.sha256(b''.join(len(s.encode()).to_bytes(8, 'big') + s.encode()
                                   for s in parts)).hexdigest()
    rng = random.Random(int(seed, 16))
    beat = 60 / params['tempo']
    duration = 32 * beat
    mix = [0.0] * int(duration * RATE)
    scale = [0, 2, 4, 5, 7, 9, 11] if params['mode'] == 'major' else [0, 2, 3, 5, 7, 8, 10]

    def note(degree):
        octave, index = divmod(degree, 7)
        return params['root'] + scale[index] + 12 * octave

    def tone(start, length, midi, volume, pad=False):
        frequency = 440 * 2 ** ((midi - 69) / 12)
        offset = int(start * RATE)
        count = min(int(length * RATE), len(mix) - offset)
        bright = params['brightness']
        for i in range(count):
            t = i / RATE
            attack = min(1, t / (.06 if pad else .008))
            release = min(1, (count - i) / (RATE * .04))
            env = attack * release * math.exp(-t / (length * (.8 if pad else .35)))
            phase = TAU * frequency * t
            sample = math.sin(phase) + bright * .35 * math.sin(2 * phase) + bright * .16 * math.sin(3 * phase)
            mix[offset + i] += volume * env * sample

    def drum(start, kind):
        length = {'kick': .3, 'snare': .18, 'hat': .055}[kind]
        offset = int(start * RATE)
        for i in range(min(int(length * RATE), len(mix) - offset)):
            t = i / RATE
            if kind == 'kick':
                phase = TAU * (45 * t + 100 * .025 * (1 - math.exp(-t / .025)))
                sample = .65 * math.sin(phase) * math.exp(-t * 15)
            elif kind == 'snare':
                sample = .24 * (rng.uniform(-1, 1) + .35 * math.sin(TAU * 180 * t)) * math.exp(-t * 25)
            else:
                sample = .12 * rng.uniform(-1, 1) * math.exp(-t * 75)
            mix[offset + i] += sample

    position = rng.randrange(7, 12)
    for bar in range(8):
        degree = params['progression'][bar % 4]
        start = bar * 4 * beat
        for third in (0, 2, 4):
            tone(start, 4 * beat, note(degree + third), .075, pad=True)
        for step in range(8):
            when = start + step * beat / 2
            if step % 2 == 0:
                tone(when, beat * .85, note(degree) - 12, .24 * params['bass_weight'])
            if rng.random() < params['melody_density']:
                position = max(7, min(20, position + rng.choice([-2, -1, 0, 1, 2])))
                tone(when, beat * rng.choice([.4, .7, .95]), note(position), .14)
            density = params['drum_density']
            if density > 0:
                if step in (0, 4) or rng.random() < density * .18:
                    drum(when, 'kick')
                if step in (2, 6) and rng.random() < min(1, density * 1.8):
                    drum(when, 'snare')
                if rng.random() < density:
                    drum(when, 'hat')
    # Soft saturation, normalization, and an end fade prevent clipping and clicks.
    clipped = [math.tanh(value) for value in mix]
    gain = 30000 / max(max(abs(v) for v in clipped), .001)
    samples = array.array('h', (int(v * gain * min(1, i / (RATE * .01),
                           (len(mix) - 1 - i) / (RATE * .12)))
                           for i, v in enumerate(clipped)))
    if sys.byteorder != 'little':
        samples.byteswap()
    output = io.BytesIO()
    with wave.open(output, 'wb') as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(RATE)
        wav.writeframes(samples.tobytes())
    title = ' '.join(re.findall(r"[\w']+", prompt)[:6]).title() or 'Untitled Song'
    info = dict(params, title=title, feedback=feedback, seed=seed,
                sample_rate=RATE, bars=8, duration_seconds=len(mix) / RATE)
    return output.getvalue(), info
