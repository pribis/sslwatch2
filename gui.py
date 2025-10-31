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
        self.detailed_view = False # Start with compact view
        self.app_mode = 'DOMAIN_INPUT'
        self.domain_input_str = ""
        self.popup_active = False

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
        self.input_win.timeout(100) # Set non-blocking on the window that gets input
        self.stdscr.timeout(100) # Set a non-blocking timeout on the main screen
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
        help_text = "Ctrl-X: Help  |  Ctrl-C: Quit"
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
        return False # Reset redraw flag

    def run(self):
        redraw = True
        while True:
            # First, draw the screen if a redraw is needed.
            redraw = self._draw(redraw)
            curses.doupdate() # Perform all staged refreshes

            # Now, wait for input. This is the only blocking call in the main loop.
            try:
                # Get input from the window that has the cursor
                key_pressed = self.input_win.getch()
            except curses.error:
                key_pressed = -1

            # Process input
            if key_pressed == -1:
                pass # Timeout, do nothing
            elif key_pressed == curses.KEY_MOUSE:
                try:
                    _, mx, my, _, _ = curses.getmouse()
                    if self.output_win.enclose(my, mx):
                        self._handle_mouse_click(my, mx)
                except curses.error:
                    pass # Ignore mouse errors
                redraw = True
            elif key_pressed == 6: # Ctrl-F
                self.app_mode = 'FILE_INPUT' if self.app_mode == 'DOMAIN_INPUT' else 'DOMAIN_INPUT'
                self.domain_input_str = ""
                redraw = True
            elif key_pressed == 4: # Ctrl-D
                self.detailed_view = not self.detailed_view
                self.scroll_pos = 0
                redraw = True
            elif key_pressed == 24: # Ctrl-X
                # This must be the last action for this key.
                # It will block until the popup is closed.
                self._display_help_popup()
                redraw = True # Redraw main screen after popup closes
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
                        threading.Thread(target=self.checker_functions['ssl'], args=(input_str, self.result_queue)).start()
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
                                    threading.Thread(target=self.checker_functions['ssl'], args=(domain, self.result_queue)).start()
                        except FileNotFoundError:
                            self.results_list = [{"status": "ERROR", "message": f"File not found: '{input_str}'"}]
                        self.app_mode = 'DOMAIN_INPUT'
                    self.domain_input_str = ""
                    redraw = True
            elif 32 <= key_pressed <= 126:
                self.domain_input_str += chr(key_pressed)
                redraw = True

            # Process results from the queue
            redraw_main = False
            while not self.result_queue.empty():
                try:
                    # Peek at the result without removing it
                    result = self.result_queue.queue[0]
                    if str(result.get("status", "")).startswith("WHOIS"):
                        break # Let the popup handle this

                    new_result = self.result_queue.get_nowait()
                    is_batch_job = self.results_list and self.results_list[0].get("status") == "INFO"
                    if self.active_threads > 0: self.active_threads -= 1
                    self.results_list = [new_result] if is_batch_job else self.results_list + [new_result]
                    if is_batch_job: self.scroll_pos = 0
                    redraw_main = True
                except (queue.Empty, IndexError):
                    break
            if self.is_checking and self.active_threads == 0: self.is_checking = False
            if redraw_main: redraw = True

    def _handle_mouse_click(self, y, x):
        # Curses y,x are relative to screen, need to convert to window-relative
        win_y, win_x = self.output_win.getbegyx()
        rel_y = y - win_y

        if not (1 <= rel_y < self.output_win.getmaxyx()[0] - 1):
            return # Click was on border or outside

        lines_per_block = 7 if self.detailed_view else 1
        clicked_index = self.scroll_pos + ((rel_y - 1) // lines_per_block)

        if 0 <= clicked_index < len(self.results_list):
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
            # --- Draw Popup ---
            popup_win.erase()
            popup_win.box()
            popup_win.addstr(0, 2, f" Whois: {domain} (Q to close) ")
            popup_win.addstr(0, popup_w - 2, 'x', curses.A_BOLD) # Add close button

            if whois_data is None:
                popup_win.addstr(2, 2, "Fetching whois data, please wait...")
            else:
                data = whois_data.get("data", "No data available.")
                lines = data.split('\n')
                max_lines = popup_h - 2
                for i, line in enumerate(lines[scroll_pos:]):
                    if i >= max_lines: break
                    popup_win.addstr(i + 1, 2, line[:popup_w-3])

            popup_win.refresh()

            # --- Check for whois result ---
            if whois_data is None:
                try:
                    result = self.result_queue.get_nowait()
                    if result.get("status", "").startswith("WHOIS"):
                        whois_data = result
                except queue.Empty:
                    pass

            # --- Handle Input ---
            try:
                key = popup_win.getch()
            except curses.error:
                key = -1

            if key == curses.KEY_MOUSE:
                try:
                    _, mx, my, _, bstate = curses.getmouse() # bstate is a bitmask

                    # Check for close button click
                    rel_y, rel_x = my - popup_y, mx - popup_x
                    is_left_click = (hasattr(curses, 'BUTTON1_PRESSED') and bstate & curses.BUTTON1_PRESSED) or \
                                    (hasattr(curses, 'BUTTON1_CLICKED') and bstate & curses.BUTTON1_CLICKED)

                    if is_left_click and rel_y == 0 and rel_x == popup_w - 2:
                        break # Close the popup

                    # Check for scroll wheel up (BUTTON4_PRESSED)
                    elif hasattr(curses, 'BUTTON4_PRESSED') and bstate & curses.BUTTON4_PRESSED:
                        scroll_pos = max(0, scroll_pos - 3) # Scroll by 3 lines for a better feel
                    # Check for scroll wheel down (BUTTON5_PRESSED)
                    elif hasattr(curses, 'BUTTON5_PRESSED') and bstate & curses.BUTTON5_PRESSED:
                        if whois_data and whois_data.get('data'):
                            max_scroll = len(whois_data['data'].split('\n')) - (popup_h - 2)
                            scroll_pos = min(max(0, max_scroll), scroll_pos + 3)
                except curses.error:
                    pass # Ignore mouse errors
            elif key in [ord('q'), ord('Q')]:
                break
            elif key == curses.KEY_UP:
                scroll_pos = max(0, scroll_pos - 1)
            elif key == curses.KEY_DOWN:
                if whois_data and whois_data.get('data'):
                    max_scroll = len(whois_data['data'].split('\n')) - (popup_h - 2)
                    scroll_pos = min(max(0, max_scroll), scroll_pos + 1)

        # Cleanup
        del popup_win
        self.stdscr.touchwin()
        self.stdscr.refresh()

    def _display_help_popup(self):
        h, w = self.stdscr.getmaxyx()
        popup_h, popup_w = 15, 80
        popup_y, popup_x = (h - popup_h) // 2, (w - popup_w) // 2
        popup_win = curses.newwin(popup_h, popup_w, popup_y, popup_x)
        popup_win.keypad(True)
        popup_win.timeout(100) # Use a non-blocking getch, essential for the loop

        help_lines = [
            ("General", ""),
            ("  Enter", "Check a single domain."),
            ("  Ctrl-F", "Toggle file input mode to check domains from a file."),
            ("  Ctrl-C", "Quit the application."),
            ("", ""),
            ("Navigation", ""),
            ("  Ctrl-D", "Toggle between compact and detailed results view."),
            ("  ← / →", "Page through results list."),
            ("  Mouse Click", "On a domain to view its WHOIS information."),
            ("  Ctrl-X", "Display this help screen."),
            ("Popups (WHOIS/Help)", ""),
            ("  Q / Esc", "Close the active popup window."),
            ("  ↑ / ↓", "Scroll content within a popup."),
        ]

        # Flush any lingering input before waiting for a new key press
        curses.flushinp()

        self.popup_active = True
        # This loop structure is essential for the popup to control the screen
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

            # Wait for a specific key to close, ignoring the initial Ctrl-H.
            key = popup_win.getch()
            if key != -1: # Break on any key press
                break

        # Cleanup
        del popup_win
        self.stdscr.touchwin()
        self.stdscr.refresh()