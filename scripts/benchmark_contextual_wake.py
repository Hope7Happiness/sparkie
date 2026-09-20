"""Small synthetic check of the production contextual router; live calls are opt-in."""
import argparse
import asyncio
import json
import time
from pathlib import Path

from sparkie.wake_router import DevinWakeRouter, INSTRUCTION


def human(text, speaker='Oliver', speaker_id='zoom:10'):
    return dict(role='human', text=text, speaker=speaker, speaker_id=speaker_id)


def assistant(text):
    return dict(role='assistant', speaker='Sparkie', text=text,
                delivery='generated_audio_not_verified')


CASES = [
    ('answer_to_assistant', [assistant('Would you like the short or detailed version?')],
     human('The short version, please.'), 'accept'),
    ('followup', [human('Sparkie, compare SQLite and Postgres.'),
                  assistant('SQLite is simpler locally; Postgres supports concurrent writers.')],
     human('And which would you recommend for our prototype?'), 'accept'),
    ('correction', [human('Sparkie, research five options.'), assistant('I will research five options.')],
     human('Actually, make it three and focus on open source.'), 'accept'),
    ('answer_to_human', [human('Oliver, short or detailed?', 'Maya', 'zoom:20')],
     human('The short version, please.'), 'reject'),
    ('switch_to_human', [assistant('SQLite is a good fit for this prototype.')],
     human('Maya, do you agree with that?'), 'reject'),
    ('third_person', [], human('Sparkie is our meeting assistant.'), 'reject'),
    ('quoted_wake', [], human('The demo script says: Hey Sparkie, summarize the meeting.'), 'reject'),
    ('acknowledgment', [assistant('The answer is forty-two.')], human('Thanks, that is all.'), 'reject'),
    ('ambiguous_without_context', [], human('The short version, please.'), 'reject'),
    ('eight_entry_window', [human('Sparkie, compare our storage options.'),
        assistant('SQLite is easy to deploy locally.'), human('What about concurrency?'),
        assistant('Postgres supports multiple concurrent writers.'),
        human('Our prototype runs locally.', 'Maya', 'zoom:20'), human('We only need one writer.'),
        human('Keep deployment simple.', 'Maya', 'zoom:20'),
        assistant('Would you like me to turn this into a recommendation?')],
     human('Yes, please, with the tradeoffs.'), 'accept'),
]


async def run():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    report = {'live': args.live, 'instruction': INSTRUCTION, 'cases': []}
    router = DevinWakeRouter() if args.live else None
    try:
        if router:
            await router.start()
            report['model'] = router.model
        for name, context, current, expected in CASES:
            row = dict(name=name, context=context, current=current, expected=expected)
            if router:
                started = time.monotonic()
                try:
                    row['decision'] = await router.classify(current['text'], context=context,
                        speaker=current['speaker'], speaker_id=current['speaker_id'])
                except Exception as exc:
                    row['error_type'] = type(exc).__name__
                row['latency_ms'] = round((time.monotonic() - started) * 1000)
                row['matched'] = row.get('decision') == expected
            report['cases'].append(row)
            print(json.dumps({k: v for k, v in row.items() if k not in ('context', 'current')}), flush=True)
    finally:
        if router:
            await router.close()
    if args.output:
        args.output.write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__':
    asyncio.run(run())
