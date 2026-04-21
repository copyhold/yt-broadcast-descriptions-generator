#!/usr/bin/env python3
import argparse
import os
import sys

from dotenv import load_dotenv

import gemini_client
import processor

load_dotenv()


def parse_args():
    parser = argparse.ArgumentParser(
        description='Generate church service outlines and update YouTube descriptions.',
    )
    parser.add_argument('--channel-id', required=True, help='YouTube channel ID (UCxxxxxx...)')
    parser.add_argument(
        '--primary-lang',
        choices=['he', 'ru', 'en'],
        default='he',
        help='Primary language to transcribe from (default: he)',
    )
    parser.add_argument(
        '--limit',
        type=int,
        default=10,
        help='Number of recent videos to check (default: 10)',
    )
    parser.add_argument(
        '--credentials',
        default=os.getenv('YOUTUBE_CREDENTIALS', 'client_secret.json'),
        help='Path to Google OAuth2 client_secret.json',
    )
    parser.add_argument(
        '--gemini-api-key',
        default=os.getenv('GEMINI_API_KEY'),
        help='Gemini API key (or set GEMINI_API_KEY env var)',
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Generate outlines but do not update YouTube descriptions',
    )
    return parser.parse_args()


def main():
    args = parse_args()

    if not args.gemini_api_key:
        print('Error: Gemini API key is required. Set --gemini-api-key or GEMINI_API_KEY env var.')
        sys.exit(1)

    if not os.path.exists(args.credentials):
        print(f'Error: credentials file not found: {args.credentials}')
        sys.exit(1)

    processor.run(
        channel_id=args.channel_id,
        primary_lang=args.primary_lang,
        limit=args.limit,
        credentials_file=args.credentials,
        gemini_api_key=args.gemini_api_key,
        dry_run=args.dry_run,
    )

    stats = gemini_client.get_token_stats()
    print(
        f'\nToken usage — input: {stats["input"]:,}  output: {stats["output"]:,}  total: {stats["total"]:,}'
    )


if __name__ == '__main__':
    main()
