#!/usr/bin/env python3
"""Functional chatbot smoke checks; no performance or quality benchmark."""
import argparse
import datetime
import json
import os
from pathlib import Path
import time
import requests

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--service-root', required=True)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--long', action='store_true')
    parser.add_argument('--ca-bundle', type=Path)
    parser.add_argument('--local-container', action='store_true', help='Use only for an authorized container-local route; skips gateway authentication checks')
    args = parser.parse_args()
    base = args.service_root.rstrip('/')
    if 'CHANGE_ME' in base or not base.startswith(('https://', 'http://')) or base.endswith('/v1'):
        parser.error('Provide the actual invocation prefix, before custom /v1 paths')
    if not args.local_container and not base.startswith('https://'):
        parser.error('Use the HTTPS ModelArts invocation route; HTTP is permitted only for an authorized container-local test')
    key = os.environ.get('QWEN_MODELARTS_API_KEY')
    if not args.local_container and not key:
        parser.error('Set QWEN_MODELARTS_API_KEY without placing it in a command argument')
    if args.ca_bundle and not args.ca_bundle.is_file():
        parser.error('CA bundle does not exist')
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    session = requests.Session()
    session.verify = str(args.ca_bundle) if args.ca_bundle else True
    if key:
        session.headers['Authorization'] = 'Bearer ' + key
    model = 'qwen3.6-35b-a3b'
    results = []

    def save(name, data):
        (out / name).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')

    def post(path, body, timeout=1200):
        start = time.monotonic()
        response = session.post(base + path, json=body, timeout=timeout)
        response.raise_for_status()
        return response.json(), time.monotonic() - start

    assert session.get(base + '/health', timeout=20).status_code == 200
    response = session.get(base + '/v1/models', timeout=20)
    response.raise_for_status()
    models = response.json()
    save('models.json', models)
    entry = next(x for x in models['data'] if x['id'] == model)
    if entry.get('max_model_len') is not None:
        assert entry['max_model_len'] == 262144, entry
    results.append({'case': 'model_listing', 'passed': True, 'reported_context': entry.get('max_model_len')})
    cases = [
        ('basic', [{'role': 'user', 'content': 'Return only the integer result of 19 + 24.'}], '43'),
        ('unicode', [{'role': 'user', 'content': 'Copy exactly this text without quotes or commentary: Olá, Brasil! 你好！'}], 'Olá, Brasil! 你好！'),
        ('multiturn', [{'role': 'system', 'content': 'You are a helpful chatbot. Answer concisely.'},
                       {'role': 'user', 'content': 'My favorite color is turquoise.'},
                       {'role': 'assistant', 'content': 'I will remember turquoise.'},
                       {'role': 'user', 'content': 'What is my favorite color? Return only its name.'}], 'turquoise')
    ]
    for name, messages, expected in cases:
        data, elapsed = post('/v1/chat/completions', {'model': model, 'messages': messages,
                              'max_tokens': 256, 'temperature': 0, 'chat_template_kwargs': {'enable_thinking': False}})
        save(name + '.json', data)
        answer = data['choices'][0]['message']['content'].strip()
        assert answer.strip('"').lower() == expected.lower(), (name, answer)
        assert data['choices'][0]['finish_reason'] == 'stop'
        results.append({'case': name, 'passed': True, 'seconds': elapsed, 'usage': data.get('usage')})

    body = {'model': model, 'messages': [{'role': 'user', 'content': 'Return exactly this JSON with no formatting: {"answer":43,"text":"Olá 你好"}'}],
            'max_tokens': 256, 'temperature': 0, 'stream': True, 'stream_options': {'include_usage': True},
            'chat_template_kwargs': {'enable_thinking': False}}
    start = time.monotonic()
    with session.post(base + '/v1/chat/completions', json=body, stream=True, timeout=1200) as response:
        response.raise_for_status()
        answer, done, events = '', False, []
        for line in response.iter_lines():
            if not line.startswith(b'data: '):
                continue
            payload = line[6:].decode('utf-8')
            if payload == '[DONE]':
                done = True
                break
            event = json.loads(payload)
            events.append(event)
            for choice in event.get('choices', []):
                answer += choice.get('delta', {}).get('content') or ''
    save('stream.json', {'events': events, 'done': done, 'content': answer})
    assert done and json.loads(answer) == {'answer': 43, 'text': 'Olá 你好'}
    results.append({'case': 'stream_unicode_json', 'passed': True, 'seconds': time.monotonic() - start})

    data, elapsed = post('/v1/chat/completions', {'model': model,
                        'messages': [{'role': 'user', 'content': 'What is 7 plus 8? Give only the final integer.'}],
                        'max_tokens': 512, 'temperature': 0})
    save('default-thinking.json', data)
    message = data['choices'][0]['message']
    assert message['content'].strip() == '15'
    assert message.get('reasoning') or message.get('reasoning_content'), 'Default reasoning field is empty'
    assert data['choices'][0]['finish_reason'] == 'stop'
    results.append({'case': 'default_thinking', 'passed': True, 'seconds': elapsed, 'usage': data.get('usage')})

    if args.long:
        def messages(n):
            return [{'role': 'user', 'content': 'Read this filler document.\n' + (' neutral text.' * n) +
                     '\nThe secret marker is QWEN256KOK. Return only the secret marker.'}]
        n = 85000
        for attempt in range(5):
            tokens, _ = post('/tokenize', {'model': model, 'messages': messages(n),
                             'add_generation_prompt': True, 'chat_template_kwargs': {'enable_thinking': False}})
            count = tokens['count']
            save(f'long-token-count-{attempt}.json', {'repetitions': n, 'count': count})
            if 261000 <= count <= 262016:
                break
            n = int(n * (261800 / max(count, 1)))
        assert 261000 <= count <= 262016, count
        data, elapsed = post('/v1/chat/completions', {'model': model, 'messages': messages(n),
                             'max_tokens': 128, 'temperature': 0, 'chat_template_kwargs': {'enable_thinking': False}})
        save('long-context.json', data)
        assert data['choices'][0]['message']['content'].strip() == 'QWEN256KOK'
        assert data['choices'][0]['finish_reason'] == 'stop'
        assert data['usage']['prompt_tokens'] >= 261000
        results.append({'case': 'near_262144_context', 'passed': True, 'seconds': elapsed, 'usage': data['usage']})
        rejected = session.post(base + '/v1/chat/completions', json={'model': model, 'messages': messages(n + 1000),
                                'max_tokens': 128, 'chat_template_kwargs': {'enable_thinking': False}}, timeout=120)
        save('over-context.json', {'http': rejected.status_code, 'response': rejected.json()})
        assert rejected.status_code == 400
        results.append({'case': 'over_context_rejected', 'passed': True})

    if not args.local_container:
        unauthenticated = requests.Session()
        unauthenticated.verify = session.verify
        rejected = unauthenticated.post(base + '/v1/chat/completions', json={'model': model,
                                         'messages': [{'role': 'user', 'content': 'Hi'}], 'max_tokens': 4}, timeout=20)
        save('authentication-negative.json', {'status': rejected.status_code, 'body': rejected.text[:1000]})
        assert rejected.status_code in (401, 403)
        results.append({'case': 'missing_key_rejected', 'passed': True})
    assert session.get(base + '/health', timeout=20).status_code == 200
    save('summary.json', {'passed': True, 'at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
                         'service_root': base, 'results': results, 'performance_claim': False,
                         'gateway_authentication_checked': not args.local_container})
    print(json.dumps({'passed': True, 'results': results}, ensure_ascii=False), flush=True)

if __name__ == '__main__':
    main()
