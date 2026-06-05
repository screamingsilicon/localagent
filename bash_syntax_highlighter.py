import re

class BashScanner:
    def __init__(self):
        # A much improved, modern, and aesthetically pleasing color palette
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

        # The regex is now much smarter and handles strings and punctuation correctly
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
            
            # --- State Machine Logic ---
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

            # Apply color and append
            tokens.append(f"{self.C.get(token_type, '')}{val}{self.C['reset']}")
            
        return "".join(tokens)
