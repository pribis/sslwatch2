import curses
import threading
import queue

class GUI:
    def __init__(self, stdscr, checker_function):
        self.stdscr = stdscr
        self.checker_function = checker_function
        self._setup_curses()
        self._create_windows()

        # --- State ---
        self.result_queue = queue.Queue()
        self.results_list = []
        self.active_threads = 0
        self.is_checking = False
        self.scroll_pos = 0
        self.detailed_view = False # Start with compact view
        self.app_mode = 'DOMAIN_INPUT'
        self.domain_input_str = ""

    def _setup_curses(self):
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
        self.output_win = curses.newwin(h - output_win_y - 2, w - 4, output_win_y, 2)

    def _draw_output_window(self):
        win = self.output_win
        win.erase()
        win.box()
        h, w = win.getmaxyx()

        if not self.results_list:
            win.addstr(0, 2, " Result ")
            win.addstr(2, 2, "Enter a domain name above and press Enter.")
            win.noutrefresh()
            return

        lines_per_block = 7 if self.detailed_view else 1
        page_size = max(1, (h - 2) // lines_per_block)
        total_pages = max(1, (len(self.results_list) + page_size - 1) // page_size) if page_size > 0 else 1
        current_page = min(total_pages, (self.scroll_pos // page_size) + 1)

        if len(self.results_list) > 1 and total_pages > 1:
            win.addstr(0, 2, f" Results: {len(self.results_list)} Page: {current_page}/{total_pages} ")
        else:
            win.addstr(0, 2, f" Results: {len(self.results_list)} ")

        current_display_line = 1
        for result in self.results_list[self.scroll_pos:]:
            if current_display_line + lines_per_block > h - 1:
                break

            status = result.get("status", "ERROR")
            color = self.colors.get(status, curses.color_pair(0))

            if status in ["INFO", "ERROR", "UNKNOWN"]:
                lines_needed = 2
                if current_display_line + lines_needed > h - 1: break
                win.addstr(current_display_line, 2, f"Domain: {result.get('domain', 'N/A')}", color)
                win.addstr(current_display_line + 1, 2, result.get("message"))
                current_display_line += lines_needed
            elif self.detailed_view:
                win.addstr(current_display_line, 2, f"Domain:     {result.get('domain', 'N/A')}")
                win.addstr(current_display_line + 1, 2, f"Subject:    {result.get('subject_cn', 'N/A')}")
                win.addstr(current_display_line + 2, 2, f"Issuer:     {result.get('issuer_cn', 'N/A')}")
                win.addstr(current_display_line + 3, 2, f"Issued:     {result.get('issued_on', 'N/A')}")
                win.addstr(current_display_line + 4, 2, f"Expires:    {result.get('expires_on', 'N/A')} ({result.get('days_left', 'N/A')} days)")
                win.addstr(current_display_line + 5, 2, "Status:     ")
                win.addstr(current_display_line + 5, 14, result.get('status', 'N/A'), color | curses.A_BOLD)
                current_display_line += lines_per_block
            else: # Compact view
                domain_str = result.get('domain', 'N/A')
                status_str = result.get('status', 'N/A')
                display_str = f"{domain_str} "
                win.addstr(current_display_line, 2, display_str)
                win.addstr(current_display_line, 2 + len(display_str), status_str, color | curses.A_BOLD)
                current_display_line += lines_per_block
        win.noutrefresh()

    def _draw(self, redraw):
        if not redraw: return False
        h, w = self.stdscr.getmaxyx()
        self.stdscr.erase()
        self.stdscr.addstr(1, (w - 27) // 2, "SSL Certificate Checker", curses.A_BOLD | curses.A_UNDERLINE)
        prompt = "Enter domain name:" if self.app_mode == 'DOMAIN_INPUT' else "Enter file path:"
        self.stdscr.addstr(3, (w - len(prompt)) // 2, prompt)
        help_text = "Enter: Check | Ctrl-F: File | Ctrl-D: Details | Ctrl-C: Quit"
        if self.results_list: help_text += " | ←/→: Page"
        self.stdscr.addstr(h - 2, 2, help_text)
        self.stdscr.noutrefresh()

        self.input_win.erase()
        self.input_win.box()
        label_text = " Domain Input " if self.app_mode == 'DOMAIN_INPUT' else " Import Domains "
        self.input_win.addstr(0, 2, f" {label_text} ")
        self.input_win.addstr(1, 2, self.domain_input_str)
        self.input_win.noutrefresh()

        self._draw_output_window()
        self.input_win.move(1, 2 + len(self.domain_input_str))
        curses.doupdate()
        return False # Reset redraw flag

    def _process_results_queue(self):
        redraw = False
        while not self.result_queue.empty():
            try:
                is_batch_job = self.results_list and self.results_list[0].get("status") == "INFO"
                new_result = self.result_queue.get_nowait()
                if self.active_threads > 0: self.active_threads -= 1
                if is_batch_job:
                    self.results_list = [new_result]
                    self.scroll_pos = 0
                else:
                    self.results_list.append(new_result)
                redraw = True
            except queue.Empty:
                break
        if self.is_checking and self.active_threads == 0: self.is_checking = False
        return redraw

    def run(self):
        redraw = True
        while True:
            redraw = self._draw(redraw)
            try: key_pressed = self.input_win.getch()
            except curses.error: key_pressed = -1

            if key_pressed == -1: pass
            elif key_pressed == 6: # Ctrl-F
                self.app_mode = 'FILE_INPUT' if self.app_mode == 'DOMAIN_INPUT' else 'DOMAIN_INPUT'
                self.domain_input_str = ""
                redraw = True
            elif key_pressed == 4: # Ctrl-D
                self.detailed_view = not self.detailed_view
                self.scroll_pos = 0
                redraw = True
            elif key_pressed == curses.KEY_LEFT:
                lines_per_block = 7 if self.detailed_view else 1
                page_size = max(1, (self.output_win.getmaxyx()[0] - 2) // lines_per_block)
                if self.scroll_pos > 0:
                    self.scroll_pos = max(0, self.scroll_pos - page_size)
                    redraw = True
            elif key_pressed == curses.KEY_RIGHT:
                lines_per_block = 7 if self.detailed_view else 1
                page_size = max(1, (self.output_win.getmaxyx()[0] - 2) // lines_per_block)
                if self.scroll_pos + page_size < len(self.results_list):
                    self.scroll_pos += page_size
                    redraw = True
            elif key_pressed in [curses.KEY_BACKSPACE, 127, 8]:
                self.domain_input_str = self.domain_input_str[:-1]
                redraw = True
            elif key_pressed in [10, 13, curses.KEY_ENTER]:
                if not self.is_checking and self.domain_input_str.strip():
                    input_str = self.domain_input_str.strip()
                    if self.app_mode == 'DOMAIN_INPUT':
                        self.is_checking = True
                        self.results_list = [{"status": "INFO", "message": f"Please wait, checking SSL cert for '{input_str}'..."}]
                        self.scroll_pos = 0
                        threading.Thread(target=self.checker_function, args=(input_str, self.result_queue)).start()
                    else: # FILE_INPUT mode
                        try:
                            with open(input_str, 'r') as f:
                                domains = [line.strip() for line in f if line.strip()]
                            if domains:
                                self.is_checking = True
                                self.results_list = [{"status": "INFO", "message": f"Processing {len(domains)} domains from '{input_str}'..."}]
                                self.active_threads = len(domains)
                                self.scroll_pos = 0
                                for domain in domains:
                                    threading.Thread(target=self.checker_function, args=(domain, self.result_queue)).start()
                        except FileNotFoundError:
                            self.results_list = [{"status": "ERROR", "message": f"File not found: '{input_str}'"}]
                        self.app_mode = 'DOMAIN_INPUT'
                    self.domain_input_str = ""
                    redraw = True
            elif 32 <= key_pressed <= 126:
                self.domain_input_str += chr(key_pressed)
                redraw = True

            if self._process_results_queue():
                redraw = True