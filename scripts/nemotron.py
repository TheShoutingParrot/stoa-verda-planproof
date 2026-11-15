"""Run image-grounded counting on a single drawing through a server-side chat API."""

import argparse
import base64
import hashlib
import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path
import re
import socket
import sys
import tempfile
import time
from urllib import error, parse, request


MODEL = 'nvidia/nemotron-3.5-super-vl-120b-a12b'
QUESTION = 'Kuinka monta makuuhuonetta (MH) pohjapiirustuksessa on?'
INSTRUCTIONS = '''Count only the requested object type in the supplied drawing. Inspect the actual image.
For a residential Finnish plan, honor the apartment boundary: count only rooms inside the highlighted apartment if surrounding units are also drawn. Ignore rooms outside it. For a bedroom, look for labels such as MH, MAKUUH., MAKUUH or MAKUUHUONE (case-insensitive), or clear room-specific visual evidence. Do not count a legend, furniture, or duplicate labels as additional rooms.
Return a single JSON object. Use status "answered" only when the full count is supported. Give an integer answer and one evidence item per counted object: {"label":"short visible identifier or description","box":[left,top,right,bottom]}. Each box must tightly enclose the visible room label or distinguishing feature, in TOP-LEFT origin coordinates normalized from 0 to 1000 independently along each image axis. If the complete relevant drawing is readable and contains no requested objects, return an answered count of 0 with an empty evidence list. If the image is unclear, incomplete, or ambiguous, use {"status":"unknown","answer":null,"evidence":[],"reason":"short explanation"}. Do not guess. Do not return a markdown table.'''


class InvalidEvidence(ValueError):
    """The response cannot support a count."""


class ConfigurationError(ValueError):
    """A safe description of missing operator configuration."""


class NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # The inference token is scoped to the operator's selected endpoint.
        return None


def endpoint_url(base):
    parts = parse.urlsplit(base)
    if (parts.scheme != 'https' or not parts.hostname or parts.username is not None
            or parts.password is not None or parts.query or parts.fragment):
        raise ConfigurationError('An explicit HTTPS inference base URL is required (without credentials, query, or fragment).')
    base = base.rstrip('/')
    return base if base.endswith('/chat/completions') else base + '/chat/completions'


def parse_count(content):
    if not isinstance(content, str):
        raise InvalidEvidence('The model did not return text.')
    content = content.strip()
    fence = re.fullmatch(r'```(?:json)?\s*(.*?)\s*```', content, flags=re.S | re.I)
    try:
        payload = json.loads(fence.group(1) if fence else content)
    except ValueError as exc:
        raise InvalidEvidence('The model did not return valid JSON.') from exc
    if not isinstance(payload, dict):
        raise InvalidEvidence('The model did not return a count object.')
    if payload.get('status') == 'unknown':
        reason = payload.get('reason')
        return {'status': 'unknown', 'answer': None, 'evidence': [],
                'reason': reason[:220] if isinstance(reason, str) and reason.strip() else 'Drawing evidence was insufficient.'}
    count, items = payload.get('answer'), payload.get('evidence')
    if (payload.get('status') != 'answered' or type(count) is not int or count < 0
            or not isinstance(items, list) or len(items) != count):
        raise InvalidEvidence('The count and number of localized objects did not match.')
    evidence, seen = [], set()
    for item in items:
        if not isinstance(item, dict):
            raise InvalidEvidence('An evidence item was missing.')
        box, label = item.get('box'), item.get('label')
        if not isinstance(label, str) or not label.strip() or not isinstance(box, list) or len(box) != 4:
            raise InvalidEvidence('An evidence item was missing a label or four coordinates.')
        if not all(type(v) in (int, float) and math.isfinite(v) and 0 <= v <= 1000 for v in box):
            raise InvalidEvidence('Evidence coordinates fell outside the drawing.')
        x0, y0, x1, y1 = box
        if x1 <= x0 or y1 <= y0 or tuple(box) in seen or (x0 == 0 and y0 == 0 and x1 == 1000 and y1 == 1000):
            raise InvalidEvidence('Evidence must identify distinct objects within the drawing.')
        seen.add(tuple(box))
        evidence.append({'label': label.strip()[:140], 'box': box})
    return {'status': 'answered', 'answer': count, 'evidence': evidence}


def token_usage(reply):
    details = reply.get('usage')
    if not isinstance(details, dict):
        return None
    def natural(v):
        return v if type(v) is int and v >= 0 else None
    out = {k: natural(details.get(k)) for k in ('prompt_tokens', 'completion_tokens', 'total_tokens')}
    for parent, k in [('prompt_tokens_details', 'cached_tokens'), ('completion_tokens_details', 'reasoning_tokens')]:
        if isinstance(details.get(parent), dict):
            out[k] = natural(details[parent].get(k))
    return {k: v for k, v in out.items() if v is not None} or None


def run(image, question, base, model, api_key, timeout=90, opener=None, *, instructions=INSTRUCTIONS,
        thinking=None, json_output=False, max_tokens=4096):
    report = {'schema_version': 1, 'status': 'unavailable', 'answer': None, 'evidence': [],
              'question': question, 'image': image.name, 'model': model, 'provider_host': None,
              'timestamp': datetime.now(timezone.utc).isoformat(timespec='seconds'),
              'served_model': None, 'latency_ms': None, 'usage': None, 'coordinate_system': 'xyxy_top_left_0_to_1000'}
    start = None
    try:
        data = image.read_bytes()
        if data.startswith(b'\x89PNG\r\n\x1a\n'):
            mime = 'image/png'
        elif data.startswith(b'\xff\xd8\xff'):
            mime = 'image/jpeg'
        else:
            raise ConfigurationError('Supply a PNG or JPEG drawing.')
        report['image_sha256'] = hashlib.sha256(data).hexdigest()
        endpoint = endpoint_url(base)
        report['provider_host'] = parse.urlsplit(endpoint).hostname
        if not api_key:
            raise ConfigurationError('No inference credential was supplied.')
        if not model.strip() or not question.strip():
            raise ConfigurationError('Supply a model name and a counting question.')
        if not 0 < timeout <= 600:
            raise ConfigurationError('Timeout must be between 1 and 600 seconds.')
        content = [{'type': 'text', 'text': question},
                   {'type': 'image_url', 'image_url': {'url': 'data:' + mime + ';base64,' + base64.b64encode(data).decode('ascii')}}]
        payload = {'model': model, 'max_tokens': max_tokens, 'stream': False,
                   'messages': [{'role': 'system', 'content': instructions}, {'role': 'user', 'content': content}]}
        if json_output:
            payload['response_format'] = {'type': 'json_object'}
        if thinking is not None:
            payload['chat_template_kwargs'] = {'enable_thinking': thinking}
        body = json.dumps(payload).encode()
        req = request.Request(endpoint, method='POST', data=body, headers={'Content-Type': 'application/json', 'Authorization': 'Bearer ' + api_key})
        start = time.monotonic()
        client = opener or request.build_opener(NoRedirect())
        with client.open(req, timeout=timeout) as response:
            reply = json.load(response)
        if not isinstance(reply, dict) or not isinstance(reply.get('choices'), list) or not reply['choices']:
            raise ConfigurationError('The inference service returned no completion.')
        report['usage'] = token_usage(reply)
        if isinstance(reply.get('model'), str):
            report['served_model'] = reply['model'][:250]
        choice = reply['choices'][0]
        if not isinstance(choice, dict) or not isinstance(choice.get('message'), dict):
            raise ConfigurationError('The inference service returned an incomplete message.')
        if choice.get('finish_reason') == 'length':
            raise InvalidEvidence('The model exhausted its output budget before confirming evidence.')
        report.update(parse_count(choice['message'].get('content')))
    except InvalidEvidence as exc:
        report.update(status='unknown', reason=str(exc))
    except error.HTTPError as exc:
        report['reason'] = 'Inference endpoint returned HTTP ' + str(exc.code) + '.'
    except (error.URLError, socket.timeout, TimeoutError):
        report['reason'] = 'Inference endpoint was unreachable or timed out.'
    except OSError:
        report['reason'] = 'The drawing or endpoint could not be read.'
    except (UnicodeDecodeError, json.JSONDecodeError):
        report['reason'] = 'The inference endpoint did not return a JSON completion.'
    except ConfigurationError as exc:
        report['reason'] = str(exc)
    except (TypeError, ValueError):
        report['reason'] = 'The provider configuration or reply was invalid.'
    finally:
        if start is not None:
            report['latency_ms'] = round((time.monotonic() - start) * 1000)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('image', type=Path)
    parser.add_argument('--question', default=QUESTION)
    parser.add_argument('--base-url', default=os.environ.get('NEMOTRON_BASE_URL', ''), help='Provider base ending /v1, or full chat completions URL; no implicit provider.')
    parser.add_argument('--model', default=os.environ.get('NEMOTRON_MODEL', MODEL))
    parser.add_argument('--api-key-env', default='NEMOTRON_API_KEY', help='Name of environment variable holding the key for this endpoint.')
    parser.add_argument('--timeout', type=int, default=90)
    parser.add_argument('--output', type=Path, help='Write the result as JSON here; default is stdout.')
    args = parser.parse_args()
    report = run(args.image, args.question, args.base_url, args.model, os.environ.get(args.api_key_env), args.timeout)
    output = json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + '\n'
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile('w', encoding='utf-8', dir=args.output.parent, delete=False) as temp:
            temp.write(output)
        os.replace(temp.name, args.output)
    else:
        sys.stdout.write(output)
    return {'answered': 0, 'unknown': 1, 'unavailable': 2}[report['status']]


if __name__ == '__main__':
    raise SystemExit(main())
