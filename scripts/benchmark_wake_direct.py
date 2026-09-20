"""Opt-in direct OpenAI API comparison on the synthetic wake-router cases."""
import argparse
import asyncio
import json
import math
import os
from pathlib import Path
import statistics
import time

import httpx
from dotenv import load_dotenv
from benchmark_wake_router import CASES, INSTRUCTION


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--env', type=Path)
    parser.add_argument('--models', nargs='+', default=['gpt-4.1-nano', 'gpt-5.4-nano'])
    parser.add_argument('--output', type=Path, default=Path('/tmp/sparkie-wake-direct.json'))
    args = parser.parse_args()
    if not args.live:
        print(json.dumps({'live': False, 'models': args.models, 'cases': len(CASES)}))
        return
    if args.env:
        load_dotenv(args.env)
    key = os.getenv('OPENAI_API_KEY')
    if not key:
        raise SystemExit('OPENAI_API_KEY is required for --live')
    results = []
    async with httpx.AsyncClient(timeout=10, headers={'Authorization': 'Bearer ' + key}) as client:
        for model in args.models:
            rows = []
            for name, text, expected in CASES:
                row = {'case': name, 'expected': expected}
                request = {'model': model, 'input': INSTRUCTION + json.dumps(text),
                           'max_output_tokens': 32, 'store': False}
                if model.startswith('gpt-5'):
                    request['reasoning'] = {'effort': 'none'}
                begin = time.perf_counter()
                try:
                    response = await client.post('https://api.openai.com/v1/responses', json=request)
                    if not response.is_success:
                        row['http_status'] = response.status_code
                        row['decision'] = 'invalid'
                        row['error'] = 'provider_error'
                    else:
                        payload = response.json()
                        row['answer'] = ''.join(part.get('text', '')
                            for item in payload.get('output', []) if item.get('type') == 'message'
                            for part in item.get('content', []) if part.get('type') == 'output_text')
                        try:
                            value = json.loads(row['answer'])
                            row['decision'] = value['decision'] if set(value) == {'decision'} and value['decision'] in ('accept', 'reject') else 'invalid'
                        except (ValueError, TypeError, KeyError):
                            row['decision'] = 'invalid'
                except httpx.HTTPError as error:
                    row['error'] = type(error).__name__
                    row['decision'] = 'invalid'
                row['decision_ms'] = round((time.perf_counter() - begin) * 1000)
                row['correct'] = row['decision'] == expected
                rows.append(row)
                print(json.dumps({'model': model, **row}), flush=True)
                if row.get('error'):
                    break
            durations = sorted(row['decision_ms'] for row in rows)
            results.append({'model': model, 'transport': 'direct_responses_api',
                            'correct': sum(row['correct'] for row in rows), 'total': len(rows),
                            'decision_p50_ms': statistics.median(durations),
                            'decision_p95_ms': durations[math.ceil(.95 * len(durations)) - 1],
                            'rows': rows})
    args.output.write_text(json.dumps(results, indent=2) + '\n')
    print(json.dumps([{k:v for k,v in result.items() if k != 'rows'} for result in results], indent=2))


if __name__ == '__main__':
    asyncio.run(main())
