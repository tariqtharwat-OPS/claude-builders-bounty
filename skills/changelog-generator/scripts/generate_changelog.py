#!/usr/bin/env python3
"""Generate a CHANGELOG.md from git history using conventional commit parsing."""

import subprocess
import re
import sys
from collections import defaultdict
from datetime import datetime


TYPE_MAP = {
    'feat': 'Features',
    'fix': 'Bug Fixes',
    'docs': 'Documentation',
    'refactor': 'Code Refactoring',
    'perf': 'Performance Improvements',
    'test': 'Tests',
    'chore': 'Chores',
    'style': 'Style Changes',
    'ci': 'CI/CD',
    'build': 'Build System',
}

PRIORITY_ORDER = [
    'Features', 'Bug Fixes', 'Documentation', 'Code Refactoring',
    'Performance Improvements', 'Tests', 'CI/CD', 'Build System',
    'Chores', 'Style Changes',
]


def get_commits(repo_path='.', limit=50, since_tag=None):
    """Fetch recent commits from git log."""
    cmd = ['git', 'log', '--oneline', '--no-merges']
    if since_tag:
        cmd.append(f'{since_tag}..HEAD')
    else:
        cmd.extend(['-n', str(limit)])
    
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=repo_path)
    if result.returncode != 0:
        print(f"Error: {result.stderr}", file=sys.stderr)
        return []
    
    return [line for line in result.stdout.strip().split('\n') if line.strip()]


def parse_commit(line):
    """Parse a commit line into type, scope, description, and hash."""
    parts = line.split(' ', 1)
    if len(parts) < 2:
        return None
    
    hash_part, message = parts[0], parts[1]
    
    # Try conventional commit formats:
    # feat: description
    # feat(scope): description  
    # fix: description
    match = re.match(r'^(\w+)(?:\(([^)]+)\))?:\s*(.+)', message)
    if match:
        commit_type, scope, desc = match.groups()
        return {
            'hash': hash_part,
            'type': commit_type.lower(),
            'scope': scope,
            'description': desc.strip(),
            'message': message.strip(),
        }
    
    # Fallback: treat as uncategorized
    return {
        'hash': hash_part,
        'type': None,
        'scope': None,
        'description': message.strip(),
        'message': message.strip(),
    }


def generate_changelog(commits, version=None, date=None):
    """Generate CHANGELOG.md content from parsed commits."""
    grouped = defaultdict(list)
    other = []
    
    for commit in commits:
        if commit is None:
            continue
            
        category = TYPE_MAP.get(commit['type'])
        
        if category:
            entry = f"- {commit['description']} ({commit['hash']})"
            if commit['scope']:
                entry = f"- **{commit['scope']}**: {commit['description']} ({commit['hash']})"
            grouped[category].append(entry)
        else:
            other.append(f"- {commit['message']} ({commit['hash']})")
    
    # Build output
    lines = ['# Changelog', '']
    
    # Version header
    ver = version or 'Unreleased'
    dt = date or datetime.now().strftime('%Y-%m-%d')
    if ver == 'Unreleased':
        lines.append(f'## [{ver}]')
    else:
        lines.append(f'## [{ver}] - {dt}')
    lines.append('')
    
    # Categorized sections
    for category in PRIORITY_ORDER:
        if category in grouped:
            lines.append(f'### {category}')
            lines.append('')
            for entry in grouped[category]:
                lines.append(entry)
            lines.append('')
    
    # Uncategorized
    if other:
        lines.append('### Other Changes')
        lines.append('')
        for entry in other:
            lines.append(entry)
        lines.append('')
    
    return '\n'.join(lines)


def main():
    import argparse
    parser = argparse.ArgumentParser(description='Generate CHANGELOG.md from git history')
    parser.add_argument('--limit', type=int, default=50, help='Max commits to include')
    parser.add_argument('--since-tag', help='Generate changelog since this tag')
    parser.add_argument('--version', help='Version string for the header')
    parser.add_argument('--output', '-o', help='Output file (default: stdout)')
    parser.add_argument('--repo', default='.', help='Repository path')
    
    args = parser.parse_args()
    
    commits_raw = get_commits(args.repo, args.limit, args.since_tag)
    commits = [parse_commit(line) for line in commits_raw]
    
    date_str = datetime.now().strftime('%Y-%m-%d')
    changelog = generate_changelog(commits, args.version, date_str)
    
    if args.output:
        with open(args.output, 'w') as f:
            f.write(changelog)
        print(f"Written {args.output}")
    else:
        print(changelog)


if __name__ == '__main__':
    main()
