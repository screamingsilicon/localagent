"""Bash syntax highlighter using regex-based tokenisation."""

from __future__ import annotations

import re


class BashScanner:
    def __init__(self):
        self.C = {
            "cmd": "\033[1;92m",      # Bold Bright Green
            "danger": "\033[1;37;41m",# Bold White on Red Background
            "flag": "\033[36m",       # Cyan
            "arg": "\033[0m",         # Reset/Default (Terminal default)
            "op": "\033[1;35m",       # Bold Magenta
            "redir": "\033[91m",      # Bright Red
            "env": "\033[94m",        # Bright Blue
            "string": "\033[33m",     # Yellow
            "punct": "\033[90m",      # Dark Gray
            "reset": "\033[0m"
        }
        
        self.danger_list = {
            'rm', 'dd', 'mkfs', 'shred', 'truncate', 'wipe', 
            'fdisk', 'parted', 'format', 'mkswap', 'mkfs.ext4'
        }
        
        # Commands that invoke other commands, keeping the "cmd" state active
        self.chain_cmds = {
            'sudo', 'xargs', 'env', 'nohup', 'time', 'watch', 
            '-exec', 'eval', 'stdbuf', 'timeout', 'do', 'then'
        }

        self.token_regex = re.compile(
            r'(?P<string>"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\')|'
            r'(?P<op>&&|\|\||\||;)|'
            r'(?P<redir>&>>|>>|>|<<|<|2>&1|&>|>&)|'
            r'(?P<env_assign>[a-zA-Z_]+=)|'
            r'(?P<space>\s+)|'
            r'(?P<punct>[()=])|'
            r'(?P<word>[^\s()=<>|&;]+)'
        )

    def process(self, command):
        """Tokenizes and colors while preserving exact whitespace."""
        tokens = []
        is_next_cmd = True
        last_was_flag_start = False
        last_was_env_assign = False
        
        for match in self.token_regex.finditer(command):
            kind = match.lastgroup
            val = match.group(kind)

            if kind == 'space':
                tokens.append(val)
                last_was_env_assign = False # Space breaks the env assignment RHS
                continue
            
            token_type = 'arg'
            
            if kind == 'op':
                token_type = 'op'
                is_next_cmd = True
                last_was_flag_start = False
                last_was_env_assign = False
                
            elif kind == 'redir':
                token_type = 'redir'
                last_was_flag_start = False
                last_was_env_assign = False
                
            elif kind == 'punct':
                token_type = 'punct'
                # Subshells and process substitution open up a new command context
                if val == '(':
                    is_next_cmd = True
                last_was_flag_start = False
                last_was_env_assign = False
                
            elif kind == 'env_assign':
                token_type = 'env'
                last_was_env_assign = True
                last_was_flag_start = False
                
            elif kind == 'string':
                token_type = 'string'
                last_was_flag_start = False
                # Don't cancel next command if this string is just the RHS of an env var assignment (like DEBUG="1" ./build.sh)
                if not last_was_env_assign:
                    is_next_cmd = False
                last_was_env_assign = False
                
            elif kind == 'word':
                if last_was_env_assign:
                    token_type = 'string'  # Color unquoted env values like strings
                    last_was_env_assign = False
                elif val.startswith('-'):
                    token_type = 'flag'
                    last_was_flag_start = (val == '-')
                    is_next_cmd = False
                elif last_was_flag_start:
                    token_type = 'flag'
                    last_was_flag_start = False
                    is_next_cmd = False
                elif is_next_cmd:
                    token_type = 'danger' if val in self.danger_list else 'cmd'
                    is_next_cmd = False
                    last_was_flag_start = False
                else:
                    token_type = 'arg'
                    last_was_flag_start = False
                
                # Modifiers like 'sudo' or '-exec' trigger another command immediately
                if val in self.chain_cmds:
                    is_next_cmd = True

            tokens.append(f"{self.C.get(token_type, '')}{val}{self.C['reset']}")
            
        return "".join(tokens)


def _highlight(source: str, show_trailing: bool = False) -> str:
    """Return an ANSI-colored version of a Bash command/script."""
    scanner = BashScanner()
    lines = source.splitlines(True)
    result_parts: list[str] = []

    for line in lines:
        colored_line = scanner.process(line)
        if show_trailing:
            stripped = line.rstrip()
            trailing = line[len(stripped):]
            if trailing:
                vis = re.sub(r' ', '·', trailing)
                vis = re.sub(r'\t', '→', vis)
                line_end = "\n" if line.endswith("\n") else ""
                without_newline = colored_line.rstrip("\n")
                colored_line = without_newline + "\033[1;31m" + vis + "\033[0m" + line_end
        result_parts.append(colored_line)

    return "".join(result_parts)


def _diff_highlight(
    old_source: str,
    new_source: str,
    old_label: str = "old",
    new_label: str = "new",
    context_lines: int = 3,
) -> str:
    """Produce a syntax-highlighted unified diff between two Bash sources."""
    from .differ import diff_highlight as _raw_diff

    old_colored = _highlight(old_source)
    new_colored = _highlight(new_source)

    return _raw_diff(
        old_source, new_source,
        old_colored=old_colored, new_colored=new_colored,
        old_label=old_label, new_label=new_label,
        context_lines=context_lines,
    )


if __name__ == "__main__":
    import sys

    show_trailing = "--trailing" in sys.argv
    if show_trailing:
        sys.argv.remove("--trailing")

    if len(sys.argv) > 1:
        with open(sys.argv[1]) as f:
            src = f.read()
    else:
        src = sys.stdin.read()

    sys.stdout.write(_highlight(src, show_trailing=show_trailing))