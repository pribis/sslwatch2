import curses
import threading
import queue


class GUI:
    def __init__(self, stdscr, checker_functions):
        self.stdscr = stdscr
        self.checker_functions = checker_functions
        self._setup_curses()
        self._create_windows()

        # --- State ---
        self.result_queue = queue.Queue()
        self.results_list = []
        self.active_threads = 0
        self.is_checking = False
        self.scroll_pos = 0
        self.detailed_view = False
        self.app_mode = 'DOMAIN_INPUT'
        self.domain_input_str = ""
        self.popup_active = False
        self.current_result_index = None
        self.focus = 'INPUT'       # 'INPUT' or 'RESULTS'
        self.selected_index = 0    # Highlighted row when focus == 'RESULTS'

    def _setup_curses(self):
        curses.mousemask(curses.ALL_MOUSE_EVENTS | curses.REPORT_MOUSE_POSITION)
        curses.curs_set(1)
        self.stdscr.keypad(True)
        curses.start_color()
        curses.use_default_colors()
        curses.init_pair(1, curses.COLOR_GREEN, -1)
        curses.init_pair(2, curses.COLOR_YELLOW, -1)
        curses.init_pair(3, curses.COLOR_RED, -1)
        curses.init_pair(4, curses.COLOR_CYAN, -1)
        self.colors = {
            "OK": curses.color_pair(1), "WARNING": curses.color_pair(2),
            "ALERT": curses.color_pair(3), "EXPIRED": curses.color_pair(3),
            "INFO": curses.color_pair(4), "ERROR": curses.color_pair(3),
            "UNKNOWN": curses.color_pair(2),
        }

    def _create_windows(self):
        h, w = self.stdscr.getmaxyx()
        input_win_y, input_win_x = 5, (w - 60) // 2
        output_win_y = 9
        self.input_win = curses.newwin(3, 60, input_win_y, input_win_x)
        self.input_win.keypad(True)
        self.input_win.timeout(100)
        self.stdscr.timeout(100)
        self.output_win = curses.newwin(h - output_win_y - 2, w - 4, output_win_y, 2)

    def _page_size(self):
        """Viewable rows in the results window (true real estate)."""
        h = self.output_win.getmaxyx()[0]
        return max(1, h - 2)

    def _item_heights(self):
        """Line height of every item in results_list."""
        block = 7 if self.detailed_view else 2
        heights = []
        for r in self.results_list:
            s = r.get("status", "ERROR")
            heights.append(1 if s == "INFO" else block)
        return heights

    def _snap_scroll(self, pos, heights):
        """Snap pos down to the nearest item-start boundary."""
        line = 0
        for h in heights:
            if line + h > pos:
                return line
            line += h
        return max(0, line - (heights[-1] if heights else 0))

    def _draw_scrollbar(self, win, total_items, scroll_pos, page_size):
        h, w = win.getmaxyx()
        track_h = h - 2
        if total_items <= page_size or track_h <= 0:
            return
        thumb_h = max(1, track_h * page_size // total_items)
        max_scroll = max(1, total_items - page_size)
        thumb_top = 1 + (track_h - thumb_h) * scroll_pos // max_scroll
        for row in range(1, 1 + track_h):
            try:
                ch = curses.ACS_BLOCK if thumb_top <= row < thumb_top + thumb_h else curses.ACS_VLINE
                win.addch(row, w - 1, ch)
            except curses.error:
                pass

    def _draw_output_window(self):
        win = self.output_win
        win.erase()
        win.box()
        h, w = win.getmaxyx()

        if not self.results_list:
            win.addstr(0, 2, " Results ")
            win.addstr(2, 2, "Enter a domain name above and press Enter.")
            win.noutrefresh()
            return

        heights = self._item_heights()
        page_size = self._page_size()          # rows of real estate
        total_lines = sum(heights)

        total_pages = max(1, (total_lines + page_size - 1) // page_size)
        if self.scroll_pos + page_size >= total_lines:
            current_page = total_pages
        else:
            current_page = self.scroll_pos // page_size + 1

        title_attr = curses.A_BOLD if self.focus == 'RESULTS' else curses.A_NORMAL
        if total_pages > 1:
            win.addstr(0, 2, f" Results: {len(self.results_list)} Page: {current_page}/{total_pages} ", title_attr)
        else:
            win.addstr(0, 2, f" Results: {len(self.results_list)} ", title_attr)

        self._draw_scrollbar(win, total_lines, self.scroll_pos, page_size)

        display_row = 1
        line_offset = 0
        for list_idx, result in enumerate(self.results_list):
            item_h = heights[list_idx]
            # Skip items entirely above the viewport
            if line_offset + item_h <= self.scroll_pos:
                line_offset += item_h
                continue
            if display_row >= h - 1:
                break

            status = result.get("status", "ERROR")
            color = self.colors.get(status, curses.color_pair(0))
            is_current = self.current_result_index is None or list_idx == self.current_result_index
            is_selected = self.focus == 'RESULTS' and list_idx == self.selected_index

            if is_selected:
                base = curses.A_REVERSE
            elif is_current:
                base = curses.A_NORMAL
            else:
                base = curses.A_DIM

            if status == "INFO":
                win.addstr(display_row, 2, result.get("message", ""), color | base)
            elif status in ["ERROR", "UNKNOWN"]:
                win.addstr(display_row, 2, f"Domain: {result.get('domain', 'N/A')}", color | base)
                if display_row + 1 < h - 1:
                    win.addstr(display_row + 1, 2, result.get("message", ""), base)
            elif self.detailed_view:
                win.addstr(display_row,     2, f"Domain:     {result.get('domain', 'N/A')}", base)
                win.addstr(display_row + 1, 2, f"Subject:    {result.get('subject_cn', 'N/A')}", base)
                win.addstr(display_row + 2, 2, f"Issuer:     {result.get('issuer_cn', 'N/A')}", base)
                win.addstr(display_row + 3, 2, f"Issued:     {result.get('issued_on', 'N/A')}", base)
                win.addstr(display_row + 4, 2, f"Expires:    {result.get('expires_on', 'N/A')} ({result.get('days_left', 'N/A')} days)", base)
                win.addstr(display_row + 5, 2, "Status:     ", base)
                win.addstr(display_row + 5, 14, result.get('status', 'N/A'), color | curses.A_BOLD | base)
            else:  # Compact view
                domain_str = result.get('domain', 'N/A')
                status_str = result.get('status', 'N/A')
                display_str = f"{domain_str} "
                win.addstr(display_row, 2, display_str, base)
                win.addstr(display_row, 2 + len(display_str), status_str, color | curses.A_BOLD | base)
                issued  = result.get('issued_on', 'N/A')
                expires = result.get('expires_on', 'N/A')
                days    = result.get('days_left', 'N/A')
                if display_row + 1 < h - 1:
                    win.addstr(display_row + 1, 4, f"Issued: {issued}  Expires: {expires} ({days} days)", base)

            line_offset += item_h
            display_row += item_h
        win.noutrefresh()

    def _draw(self, redraw):
        if not redraw: return False
        h, w = self.stdscr.getmaxyx()
        self.stdscr.erase()
        self.stdscr.addstr(1, (w - 27) // 2, "SSL Certificate Checker", curses.A_BOLD | curses.A_UNDERLINE)
        prompt = "Enter domain name:" if self.app_mode == 'DOMAIN_INPUT' else "Enter file path:"
        self.stdscr.addstr(3, (w - len(prompt)) // 2, prompt)
        self.stdscr.addstr(h - 2, 2, "Tab: Switch focus  |  ?: Help  |  Ctrl-C: Quit")
        self.stdscr.noutrefresh()

        self.input_win.erase()
        self.input_win.box()
        label_text = " Domain Input " if self.app_mode == 'DOMAIN_INPUT' else " Import Domains "
        input_title_attr = curses.A_BOLD if self.focus == 'INPUT' else curses.A_NORMAL
        self.input_win.addstr(0, 2, f" {label_text} ", input_title_attr)
        self.input_win.addstr(1, 2, self.domain_input_str)
        self.input_win.noutrefresh()

        self._draw_output_window()

        if self.focus == 'RESULTS':
            curses.curs_set(0)
        else:
            curses.curs_set(1)
            self.input_win.move(1, 2 + len(self.domain_input_str))
        return False

    def run(self):
        redraw = True
        while True:
            redraw = self._draw(redraw)
            curses.doupdate()

            try:
                key_pressed = self.input_win.getch()
            except curses.error:
                key_pressed = -1

            if key_pressed == -1:
                pass
            elif key_pressed == curses.KEY_MOUSE:
                try:
                    _, mx, my, _, _ = curses.getmouse()
                    if self.output_win.enclose(my, mx):
                        self._handle_mouse_click(my, mx)
                except curses.error:
                    pass
                redraw = True
            elif key_pressed == 9:  # Tab — switch focus
                self.focus = 'RESULTS' if self.focus == 'INPUT' else 'INPUT'
                redraw = True
            elif key_pressed == 21:  # Ctrl-U — return to input
                if self.focus == 'RESULTS':
                    self.focus = 'INPUT'
                    redraw = True
            elif key_pressed == 6:  # Ctrl-F
                self.app_mode = 'FILE_INPUT' if self.app_mode == 'DOMAIN_INPUT' else 'DOMAIN_INPUT'
                self.domain_input_str = ""
                redraw = True
            elif key_pressed == 4:  # Ctrl-D
                self.detailed_view = not self.detailed_view
                self.scroll_pos = 0
                redraw = True
            elif key_pressed == ord('?'):  # ? — help
                self._display_help_popup()
                redraw = True
            elif key_pressed == 12:  # Ctrl-L — clear results
                self.results_list = []
                self.scroll_pos = 0
                self.selected_index = 0
                self.current_result_index = None
                redraw = True
            elif key_pressed == curses.KEY_UP:
                if self.focus == 'RESULTS' and self.selected_index > 0:
                    self.selected_index -= 1
                    heights = self._item_heights()
                    item_start = sum(heights[:self.selected_index])
                    if item_start < self.scroll_pos:
                        self.scroll_pos = item_start
                    redraw = True
            elif key_pressed == curses.KEY_DOWN:
                if self.focus == 'RESULTS' and self.selected_index < len(self.results_list) - 1:
                    self.selected_index += 1
                    heights = self._item_heights()
                    item_start = sum(heights[:self.selected_index])
                    item_end = item_start + heights[self.selected_index]
                    page_size = self._page_size()
                    if item_end > self.scroll_pos + page_size:
                        self.scroll_pos = self._snap_scroll(item_end - page_size, heights)
                    redraw = True
            elif key_pressed == curses.KEY_LEFT:
                heights = self._item_heights()
                if self.scroll_pos > 0:
                    self.scroll_pos = self._snap_scroll(max(0, self.scroll_pos - self._page_size()), heights)
                    redraw = True
            elif key_pressed == curses.KEY_RIGHT:
                heights = self._item_heights()
                total_lines = sum(heights)
                page_size = self._page_size()
                if self.scroll_pos + page_size < total_lines:
                    self.scroll_pos = self._snap_scroll(self.scroll_pos + page_size, heights)
                    redraw = True
            elif key_pressed in [curses.KEY_NPAGE, ord(' ')]:  # Page Down / Space
                if self.focus == 'RESULTS':
                    heights = self._item_heights()
                    total_lines = sum(heights)
                    page_size = self._page_size()
                    new_pos = self._snap_scroll(min(max(0, total_lines - page_size), self.scroll_pos + page_size), heights)
                    self.scroll_pos = new_pos
                    # move selection to first visible item
                    line = 0
                    for i, ih in enumerate(heights):
                        if line >= self.scroll_pos:
                            self.selected_index = i
                            break
                        line += ih
                    redraw = True
            elif key_pressed in [curses.KEY_PPAGE, 2]:  # Page Up / Ctrl-B
                if self.focus == 'RESULTS':
                    heights = self._item_heights()
                    page_size = self._page_size()
                    new_pos = self._snap_scroll(max(0, self.scroll_pos - page_size), heights)
                    self.scroll_pos = new_pos
                    line = 0
                    for i, ih in enumerate(heights):
                        if line >= self.scroll_pos:
                            self.selected_index = i
                            break
                        line += ih
                    redraw = True
            elif key_pressed in [curses.KEY_BACKSPACE, 127, 8]:
                if self.focus == 'INPUT':
                    self.domain_input_str = self.domain_input_str[:-1]
                    redraw = True
            elif key_pressed in [10, 13, curses.KEY_ENTER]:
                if self.focus == 'RESULTS':
                    if 0 <= self.selected_index < len(self.results_list):
                        result = self.results_list[self.selected_index]
                        domain = result.get('domain')
                        if domain and result.get('status') not in ['INFO', 'ERROR', 'UNKNOWN']:
                            threading.Thread(target=self.checker_functions['whois'], args=(domain, self.result_queue)).start()
                            self._display_whois_popup(domain)
                            redraw = True
                elif not self.is_checking and self.domain_input_str.strip():
                    input_str = self.domain_input_str.strip()
                    if self.app_mode == 'DOMAIN_INPUT':
                        self.is_checking = True
                        self.scroll_pos = 0
                        threading.Thread(target=self.checker_functions['ssl'], args=(input_str, self.result_queue)).start()
                    else:  # FILE_INPUT mode
                        try:
                            with open(input_str, 'r') as f:
                                domains = [line.strip() for line in f if line.strip()]
                            if domains:
                                self.is_checking = True
                                self.active_threads = len(domains)
                                self.scroll_pos = 0
                                self.selected_index = 0
                                self.current_result_index = None
                                for domain in domains:
                                    threading.Thread(target=self.checker_functions['ssl'], args=(domain, self.result_queue)).start()
                        except FileNotFoundError:
                            self.results_list.insert(0, {"status": "ERROR", "message": f"File not found: '{input_str}'"})
                        self.app_mode = 'DOMAIN_INPUT'
                    self.domain_input_str = ""
                    redraw = True
            elif 32 <= key_pressed <= 126:
                if self.focus == 'INPUT':
                    self.domain_input_str += chr(key_pressed)
                    redraw = True

            # Process results from the queue
            redraw_main = False
            while not self.result_queue.empty():
                try:
                    result = self.result_queue.queue[0]
                    if str(result.get("status", "")).startswith("WHOIS"):
                        break

                    new_result = self.result_queue.get_nowait()
                    if self.active_threads > 0: self.active_threads -= 1
                    self.results_list.insert(0, new_result)
                    self.scroll_pos = 0
                    self.selected_index = 0
                    self.current_result_index = 0
                    redraw_main = True
                except (queue.Empty, IndexError):
                    break
            if self.is_checking and self.active_threads == 0: self.is_checking = False
            if redraw_main: redraw = True

    def _handle_mouse_click(self, y, x):
        win_y, win_x = self.output_win.getbegyx()
        rel_y = y - win_y

        if not (1 <= rel_y < self.output_win.getmaxyx()[0] - 1):
            return

        heights = self._item_heights()
        display_row = 1
        line_offset = 0
        clicked_index = None
        for i, item_h in enumerate(heights):
            if line_offset + item_h <= self.scroll_pos:
                line_offset += item_h
                continue
            if rel_y < display_row + item_h:
                clicked_index = i
                break
            display_row += item_h
            line_offset += item_h

        if clicked_index is not None and 0 <= clicked_index < len(self.results_list):
            self.selected_index = clicked_index
            result = self.results_list[clicked_index]
            domain = result.get('domain')
            if domain and result.get('status') not in ['INFO', 'ERROR', 'UNKNOWN']:
                threading.Thread(target=self.checker_functions['whois'], args=(domain, self.result_queue)).start()
                self._display_whois_popup(domain)

    def _display_whois_popup(self, domain):
        h, w = self.stdscr.getmaxyx()
        popup_h, popup_w = h - 6, w - 10
        popup_y, popup_x = 3, 5
        popup_win = curses.newwin(popup_h, popup_w, popup_y, popup_x)
        popup_win.keypad(True)
        popup_win.timeout(100)

        whois_data = None
        scroll_pos = 0

        self.popup_active = True
        while True:
            popup_win.erase()
            popup_win.box()
            popup_win.addstr(0, 2, f" Whois: {domain} (Esc to close) ")
            popup_win.addstr(0, popup_w - 2, 'x', curses.A_BOLD)

            if whois_data is None:
                popup_win.addstr(2, 2, "Fetching whois data, please wait...")
            else:
                data = whois_data.get("data", "No data available.")
                lines = data.split('\n')
                for i, line in enumerate(lines[scroll_pos:]):
                    if i >= popup_h - 2: break
                    popup_win.addstr(i + 1, 2, line[:popup_w - 3])

            popup_win.refresh()

            if whois_data is None:
                try:
                    result = self.result_queue.get_nowait()
                    if result.get("status", "").startswith("WHOIS"):
                        whois_data = result
                except queue.Empty:
                    pass

            try:
                key = popup_win.getch()
            except curses.error:
                key = -1

            if key == curses.KEY_MOUSE:
                try:
                    _, mx, my, _, bstate = curses.getmouse()
                    rel_y, rel_x = my - popup_y, mx - popup_x
                    is_left_click = (hasattr(curses, 'BUTTON1_PRESSED') and bstate & curses.BUTTON1_PRESSED) or \
                                    (hasattr(curses, 'BUTTON1_CLICKED') and bstate & curses.BUTTON1_CLICKED)
                    if is_left_click and rel_y == 0 and rel_x == popup_w - 2:
                        break
                    elif hasattr(curses, 'BUTTON4_PRESSED') and bstate & curses.BUTTON4_PRESSED:
                        scroll_pos = max(0, scroll_pos - 3)
                    elif hasattr(curses, 'BUTTON5_PRESSED') and bstate & curses.BUTTON5_PRESSED:
                        if whois_data and whois_data.get('data'):
                            max_scroll = len(whois_data['data'].split('\n')) - (popup_h - 2)
                            scroll_pos = min(max(0, max_scroll), scroll_pos + 3)
                except curses.error:
                    pass
            elif key in [27]:  # Esc
                break
            elif key == curses.KEY_UP:
                scroll_pos = max(0, scroll_pos - 1)
            elif key == curses.KEY_DOWN:
                if whois_data and whois_data.get('data'):
                    max_scroll = len(whois_data['data'].split('\n')) - (popup_h - 2)
                    scroll_pos = min(max(0, max_scroll), scroll_pos + 1)
            elif key in [curses.KEY_NPAGE, ord(' ')]:  # Page Down / Space
                if whois_data and whois_data.get('data'):
                    page = popup_h - 2
                    max_scroll = len(whois_data['data'].split('\n')) - page
                    scroll_pos = min(max(0, max_scroll), scroll_pos + page)
            elif key in [curses.KEY_PPAGE, 2]:  # Page Up / Ctrl-B
                scroll_pos = max(0, scroll_pos - (popup_h - 2))

        del popup_win
        self.stdscr.touchwin()
        self.stdscr.refresh()

    def _display_help_popup(self):
        h, w = self.stdscr.getmaxyx()
        popup_h, popup_w = 23, 80
        popup_y, popup_x = (h - popup_h) // 2, (w - popup_w) // 2
        popup_win = curses.newwin(popup_h, popup_w, popup_y, popup_x)
        popup_win.keypad(True)
        popup_win.timeout(100)

        help_lines = [
            ("General", ""),
            ("  Enter", "Check a single domain."),
            ("  Ctrl-F", "Toggle file input mode to check domains from a file."),
            ("  Ctrl-C", "Quit the application."),
            ("", ""),
            ("Navigation", ""),
            ("  Tab", "Switch focus between input box and results."),
            ("  Ctrl-U", "Return cursor to domain input (when results focused)."),
            ("  Ctrl-D", "Toggle between compact and detailed results view."),
            ("  ↑ / ↓", "Move selection in results (when results focused)."),
            ("  PgDn / Space", "Page down in results (when results focused)."),
            ("  PgUp / Ctrl-B", "Page up in results (when results focused)."),
            ("  ← / →", "Page through results list."),
            ("  Enter", "View WHOIS for selected domain (when results focused)."),
            ("  Mouse Click", "On a domain to view its WHOIS information."),
            ("  Ctrl-L", "Clear all results."),
            ("  ?", "Display this help screen."),
            ("Popups (WHOIS/Help)", ""),
            ("  Esc", "Close the active popup window."),
            ("  ↑ / ↓", "Scroll one line up/down."),
            ("  PgDn / Space", "Page down."),
            ("  PgUp / Ctrl-B", "Page up."),
        ]

        curses.flushinp()

        self.popup_active = True
        while True:
            popup_win.erase()
            popup_win.box()
            popup_win.addstr(0, 2, " Help (Press any key to close) ")

            for i, (key, desc) in enumerate(help_lines):
                if key:
                    popup_win.addstr(i + 1, 2, key, curses.A_BOLD)
                if desc:
                    popup_win.addstr(i + 1, 20, desc)

            popup_win.refresh()

            key = popup_win.getch()
            if key != -1:
                break

        del popup_win
        self.stdscr.touchwin()
        self.stdscr.refresh()
