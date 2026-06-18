
"""Terminal stream renderer for localagent LLM responses.

Handles incremental rendering of SSE-streamed markdown, including
code blocks, tables, XML tool tags, and native/simulated think tags.
"""

from __future__ import annotations

import re


THINK_COLOR = "\033[3;90m"
RESET = "\033[0m"


_OPEN_THINK = '<think>'
_CLOSE_THINK = '</think>'

from render_markdown import (
    render_md, MD_BLANK, _is_md_list_item,
    _is_table_line, _is_table_separator, render_table_block,
    render_fenced_code_block,
)


class StreamRenderer:
    """Accumulate and render LLM streaming chunks to the terminal."""

    def __init__(self):
        self.full_text = ""
        self.in_native_think = False
        self.in_simulated_think = False
        self.raw_buffer = ""
        self.md_buffer = ""
        self._prev_was = {"type": "other"}
        self._table_buffer: list[str] = []
        self._table_has_separator = False
        self._code_buffer: list[str] = []
        self._in_code_block = False

    def feed_reasoning(self, text: str) -> None:
        """Feed native reasoning_content from the model."""
        if not self.in_native_think:
            print("\n" + THINK_COLOR + "> ", end="", flush=True)
            self.in_native_think = True
            self.full_text += _OPEN_THINK + "\n"
        print(text, end="", flush=True)
        self.full_text += text

    def feed_content(self, text: str) -> None:
        """Feed a content delta from the model."""
        if self.in_native_think:
            print(RESET + "\n", end="", flush=True)
            self.in_native_think = False
            self.full_text += "\n" + _CLOSE_THINK + "\n"
        self.full_text += text
        self.raw_buffer += text
        self._process_raw_buffer()

    def flush_all(self) -> None:
        """Called at end-of-stream to render any leftover partial blocks."""
        if self.in_native_think or self.in_simulated_think:
            print(RESET, end="", flush=True)

        remaining = self.md_buffer.rstrip("\n")
        if remaining.strip():
            self._handle_remaining(remaining.strip())
        self.md_buffer = ""

        if self._code_buffer:
            self._flush_code_buffer(final=True)
        if self._table_buffer:
            self._flush_table_buffer(final=True)

        if self.md_buffer.strip():
            self._flush_md_buffer()
            remaining2 = self.md_buffer.rstrip("\n")
            if remaining2.strip():
                self._handle_remaining(remaining2.strip())
            if self._code_buffer:
                self._flush_code_buffer(final=True)
            if self._table_buffer:
                self._flush_table_buffer(final=True)
            leftover = self.md_buffer.strip()
            rendered = render_md(leftover)
            if rendered is not MD_BLANK and rendered:
                prev = self._prev_was["type"]
                cur_is_header = leftover.startswith(("# ", "## ", "### "))
                if cur_is_header or prev in ("header", "list", "blank"):
                    print()
                print(rendered)

        print()

    def _process_raw_buffer(self) -> None:
        progress = True
        while self.raw_buffer and progress:
            before_len = len(self.raw_buffer)
            if not self.in_simulated_think:
                self._process_outside_think()
            else:
                self._process_inside_think()
            progress = len(self.raw_buffer) < before_len

    def _process_outside_think(self) -> None:
        if _OPEN_THINK in self.raw_buffer:
            before, _, after = self.raw_buffer.partition(_OPEN_THINK)
            if before:
                self.md_buffer += before
            self._flush_md_buffer(force=True)
            print("\n" + THINK_COLOR + "> ", end="", flush=True)
            self.in_simulated_think = True
            self.raw_buffer = after
        else:
            last_open = self.raw_buffer.rfind("<")
            if (last_open != -1
                    and not self.raw_buffer.endswith(">")
                    and ("think" + chr(62)).startswith(self.raw_buffer[last_open + 1 :])):
                self.md_buffer += self.raw_buffer[:last_open]
                self.raw_buffer = self.raw_buffer[last_open:]
                if self.md_buffer:
                    self._flush_md_buffer()
                return
            else:
                self.md_buffer += self.raw_buffer
                self.raw_buffer = ""
                self._flush_md_buffer()

    def _process_inside_think(self) -> None:
        if _CLOSE_THINK in self.raw_buffer:
            before, _, after = self.raw_buffer.partition(_CLOSE_THINK)
            print(before, end="", flush=True)
            print(RESET + "\n", end="", flush=True)
            self.in_simulated_think = False
            self.raw_buffer = after
        else:
            last_open = self.raw_buffer.rfind("<")
            if (last_open != -1
                    and not self.raw_buffer.endswith(">")
                    and ("/think" + chr(62)).startswith(self.raw_buffer[last_open + 1 :])):
                print(self.raw_buffer[:last_open], end="", flush=True)
                self.raw_buffer = self.raw_buffer[last_open:]
                return
            else:
                print(self.raw_buffer, end="", flush=True)
                self.raw_buffer = ""

    def _flush_md_buffer(self, force: bool = False) -> None:
        while self.md_buffer:
            s_stripped = self.md_buffer.lstrip(" \t\r\n")
            if not s_stripped:
                break

            block_found = False
            is_buffering_xml = False

            for tag in ("write", "edit", "shell"):
                start_sig = f"<{tag}"
                end_sig = f"</{tag}>"

                if s_stripped.startswith(start_sig):
                    end_idx = self.md_buffer.find(end_sig)
                    if end_idx != -1:
                        block_len = end_idx + len(end_sig)
                        block = self.md_buffer[:block_len]
                        self.md_buffer = self.md_buffer[block_len:]
                        if self._code_buffer:
                            self._flush_code_buffer(final=True)
                        if self._table_buffer:
                            self._flush_table_buffer(final=True)
                        rendered = render_md(block)
                        if rendered:
                            print(rendered)
                        self._prev_was["type"] = "other"
                        block_found = True
                        break
                    else:
                        is_buffering_xml = True
                        break
                elif start_sig.startswith(s_stripped):
                    is_buffering_xml = True
                    break

            if block_found:
                continue
            if is_buffering_xml:
                return

            if "\n" not in self.md_buffer:
                
                
                return

            line_end = self.md_buffer.find("\n")
            line = self.md_buffer[:line_end]
            self.md_buffer = self.md_buffer[line_end + 1:]

            stripped_line = line.strip()

            if stripped_line.startswith("```"):
                if not self._in_code_block:
                    if self._table_buffer:
                        self._flush_table_buffer(final=True)
                    self._in_code_block = True
                    self._code_buffer = [line]
                else:
                    self._code_buffer.append(line)
                    self._flush_code_buffer()
                continue

            if self._in_code_block:
                self._code_buffer.append(line)
                continue

            stripped_for_table = line.strip()
            looks_like_hr = bool(re.match(r'^[-*_]{3,}\s*$', stripped_for_table))
            if _is_table_line(line) or (_is_table_separator(line) and not looks_like_hr):
                self._table_buffer.append(line)
                if _is_table_separator(line):
                    self._table_has_separator = True
                continue

            if not line.strip():
                continue

            if self._table_buffer:
                self._flush_table_buffer(final=True)

            rendered = render_md(line)
            if rendered is MD_BLANK:
                self._prev_was["type"] = "blank"
                continue
            if not rendered:
                continue

            prev = self._prev_was["type"]
            cur_is_header = line.startswith(("# ", "## ", "### "))
            cur_is_list = _is_md_list_item(line.lstrip()) if not cur_is_header else False

            if cur_is_header:
                print()
            elif prev in ("header", "blank") and not cur_is_list:
                print()
            elif prev == "list" and not cur_is_list:
                print()
            elif prev == "other" and not cur_is_header and not cur_is_list:
                print()

            print(rendered)

            if cur_is_header:
                self._prev_was["type"] = "header"
            elif cur_is_list:
                self._prev_was["type"] = "list"
            else:
                self._prev_was["type"] = "other"

    def _flush_code_buffer(self, final: bool = False) -> None:
        if not self._code_buffer:
            return
        block = "\n".join(self._code_buffer)
        rendered = render_fenced_code_block(block)
        if rendered is not None:
            prev = self._prev_was["type"]
            if prev in ("header", "list", "blank", "other"):
                print()
            print(rendered)
            self._prev_was["type"] = "other"
        elif final:
            for line in self._code_buffer:
                print(line)
            self._prev_was["type"] = "other"
        if rendered is not None or final:
            self._code_buffer = []
            self._in_code_block = False

    def _flush_table_buffer(self, final: bool = False) -> None:
        if not self._table_buffer:
            return
        block = "\n".join(self._table_buffer)
        rendered = render_table_block(block)
        if rendered is not None:
            prev = self._prev_was["type"]
            if prev in ("header", "list", "blank", "other"):
                print()
            print(rendered)
            self._prev_was["type"] = "other"
        elif final:
            for line in self._table_buffer:
                print(line)
            self._prev_was["type"] = "other"
        if rendered is not None or final:
            self._table_buffer = []
            self._table_has_separator = False

    def _handle_remaining(self, remaining_stripped: str) -> None:
        if remaining_stripped.startswith("```"):
            if self._in_code_block:
                self._code_buffer.append(remaining_stripped)
                self._flush_code_buffer(final=True)
            else:
                if self._table_buffer:
                    self._flush_table_buffer(final=True)
                self._in_code_block = True
                self._code_buffer = [remaining_stripped]
        elif (_is_table_line(remaining_stripped)
              or (_is_table_separator(remaining_stripped)
                  and not bool(re.match(r'^[-*_]{3,}\s*$', remaining_stripped)))):
            if not self._table_buffer or self._table_buffer[-1] != remaining_stripped:
                self._table_buffer.append(remaining_stripped)
                if _is_table_separator(remaining_stripped):
                    self._table_has_separator = True
        elif self._in_code_block:
            self._code_buffer.append(remaining_stripped)
        else:
            rendered = render_md(remaining_stripped)
            if rendered is not MD_BLANK and rendered:
                print(rendered)
