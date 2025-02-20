# Copyright (C) 2023 Alessandro Iepure
#
# SPDX-License-Identifier: GPL-3.0-or-later

import glob
import logging
import os
from time import sleep
from gettext import gettext as _
from gettext import pgettext as C_
from pathlib import Path

import tmdbsimple
from gi.repository import Adw, Gio, GLib, GObject, Gtk
from requests import HTTPError

from . import shared  # type: ignore
from .background_queue import ActivityType, BackgroundActivity, BackgroundQueue
from .models.language_model import LanguageModel
from .providers.local_provider import LocalProvider as local
from .providers.tmdb_provider import TMDBProvider as tmdb


@Gtk.Template(resource_path=shared.PREFIX + '/ui/preferences.ui')
class PreferencesDialog(Adw.PreferencesDialog):
    __gtype_name__ = 'PreferencesDialog'

    _download_group = Gtk.Template.Child()
    _language_comborow = Gtk.Template.Child()
    _language_model = Gtk.Template.Child()
    _update_freq_comborow = Gtk.Template.Child()
    _offline_group = Gtk.Template.Child()
    _offline_switch = Gtk.Template.Child()
    _tmdb_group = Gtk.Template.Child()
    _use_own_key_switch = Gtk.Template.Child()
    _own_key_entryrow = Gtk.Template.Child()
    _housekeeping_group = Gtk.Template.Child()
    _exit_cache_switch = Gtk.Template.Child()
    _cache_row = Gtk.Template.Child()
    _data_row = Gtk.Template.Child()

    _tmdb_sync_row = Gtk.Template.Child()
    _tmdb_setup_page = Gtk.Template.Child()
    _tmdb_carousel = Gtk.Template.Child()
    _first_tmdb_page = Gtk.Template.Child()
    _second_tmdb_page = Gtk.Template.Child()
    _tmdb_close_btn = Gtk.Template.Child()
    _tmdb_continue_btn = Gtk.Template.Child()
    _tmdb_session_ID_btn = Gtk.Template.Child()
    _keep_tmdb_check_btn = Gtk.Template.Child()
    _keep_both_check_btn = Gtk.Template.Child()
    _tmdb_spinner = Gtk.Template.Child()
    _tmdb_radio_button_box = Gtk.Template.Child()

    request_token = ''
    session_id = ''
    account = None
    tmdb_cancel = None

    def __init__(self):
        super().__init__()
        self.language_change_handler = self._language_comborow.connect(
            'notify::selected', self._on_language_changed)
        self._update_freq_comborow.connect(
            'notify::selected', self._on_freq_changed)

        shared.schema.bind('onboard-complete', self._offline_group,
                           'sensitive', Gio.SettingsBindFlags.DEFAULT)
        shared.schema.bind('onboard-complete', self._download_group,
                           'visible', Gio.SettingsBindFlags.INVERT_BOOLEAN)
        shared.schema.bind('onboard-complete', self._tmdb_group,
                           'sensitive', Gio.SettingsBindFlags.DEFAULT)

        shared.schema.bind('offline-mode', self._offline_switch,
                           'active', Gio.SettingsBindFlags.DEFAULT)
        shared.schema.bind('use-own-tmdb-key', self._use_own_key_switch,
                           'active', Gio.SettingsBindFlags.DEFAULT)
        shared.schema.bind('exit-remove-cache', self._exit_cache_switch,
                           'active', Gio.SettingsBindFlags.DEFAULT)

        self._offline_switch.connect('notify::active', lambda pspec, user_data: logging.debug(
            f'Toggled offline mode: {self._offline_switch.get_active()}'))
        self._use_own_key_switch.connect(
            'notify::active', self._on_use_own_key_switch_activated)
        self._exit_cache_switch.connect('notify::active', lambda pspec, user_data: logging.debug(
            f'Toggled clear cache on exit: {self._exit_cache_switch.get_active()}'))

    @Gtk.Template.Callback('_on_map')
    def _on_map(self, user_data: object | None) -> None:
        """
        Callback for the "map" signal.
        Populates dropdowns and checks if an automatic update of the content is due.

        Args:
            user_data (object or None): user data passed to the callback.

        Returns:
            None
        """

        if shared.schema.get_boolean('onboard-complete'):
            self._setup_languages()

        # Update frequency dropdown
        match shared.schema.get_string('update-freq'):
            case 'never':
                self._update_freq_comborow.set_selected(0)
            case 'day':
                self._update_freq_comborow.set_selected(1)
            case 'week':
                self._update_freq_comborow.set_selected(2)
            case 'month':
                self._update_freq_comborow.set_selected(3)

        self._own_key_entryrow.set_text(
            shared.schema.get_string('own-tmdb-key'))

        # Update occupied space
        self._update_occupied_space()

    def _setup_languages(self):
        self._language_comborow.handler_block(self.language_change_handler)

        languages = local.get_all_languages()
        languages.pop(len(languages)-6)    # remove 'no language'
        for language in languages:
            self._language_model.append(language.name)

        self._language_comborow.set_selected(
            self._get_selected_language_index(shared.schema.get_string('tmdb-lang')))
        self._language_comborow.handler_unblock(self.language_change_handler)

    def _on_language_changed(self, pspec: GObject.ParamSpec, user_data: object | None) -> None:
        """
        Callback for "notify::selected" signal.
        Updates the prefered TMDB language in GSettings.

        Args:
            pspec (GObject.ParamSpec): The GParamSpec of the property which changed
            user_data (object or None): additional data passed to the callback

        Returns:
            None
        """

        language = self._get_selected_language(
            self._language_comborow.get_selected_item().get_string())
        shared.schema.set_string('tmdb-lang', language)
        logging.debug(f'Changed TMDB language to {language}')

    def _on_freq_changed(self, pspec, user_data: object | None) -> None:
        """
        Callback for "notify::selected" signal.
        Updates the frequency for content updates in GSettings.

        Args:
            pspec (GObject.ParamSpec): The GParamSpec of the property which changed
            user_data (object or None): additional data passed to the callback

        Returns:
            None
        """

        freq = self._update_freq_comborow.get_selected()
        match freq:
            case 0:
                shared.schema.set_string('update-freq', 'never')
                logging.debug(f'Changed update frequency to never')
            case 1:
                shared.schema.set_string('update-freq', 'day')
                logging.debug(f'Changed update frequency to day')
            case 2:
                shared.schema.set_string('update-freq', 'week')
                logging.debug(f'Changed update frequency to week')
            case 3:
                shared.schema.set_string('update-freq', 'month')
                logging.debug(f'Changed update frequency to month')

    def _get_selected_language_index(self, iso_name: str) -> int:
        """
        Loops all available languages and returns the index of the one with the specified iso name. If a result is not found, it returns the index for English (37).

        Args:
            iso_name: a language's iso name

        Return:
            int with the index
        """

        for idx, language in enumerate(local.get_all_languages()):
            if language.iso_name == iso_name:
                return idx
        return 37

    def _get_selected_language(self, name: str) -> str:
        """
        Loops all available languages and returns the iso name of the one with the specified name. If a result is not found, it returns the iso name for English (en).

        Args:
            name: a language's name

        Return:
            str with the iso name
        """

        for language in local.get_all_languages():
            if language.name == name:
                return language.iso_name
        return 'en'

    @Gtk.Template.Callback('_on_download_activate')
    def _on_download_activate(self, user_data: object | None) -> None:
        """
        Completes the downlaod, stores the data in the db and sets the relevant GSettings.

        Args:
            None

        Results:
            None
        """

        logging.info('Attempting first setup completetion')
        Gio.NetworkMonitor.get_default().can_reach_async(
            Gio.NetworkAddress.parse_uri('https://api.themoviedb.org', 80),
            None,
            self._on_reach_done,
            None
        )

    def _on_reach_done(self, source: GObject.Object | None, result: Gio.AsyncResult, data: object | None) -> None:
        """
        Callback for asynchronous network check, reached after the first call.
        If the network is available, proced with the download, otherwise keep checking every second until it becomes
        available or the user goes in offline mode.

        Args:
            source (GObject.Object or None): the object the asynchronous operation was started with.
            result (Gio.AsyncResult): a Gio.AsyncResult
            user_data (object or None): user data passed to the callback.

        Returns:
            None
        """

        try:
            network = Gio.NetworkMonitor.get_default().can_reach_finish(result)
        except GLib.Error:
            network = None

        if network:
            logging.error('Network ok, start download')
            languages = tmdb.get_languages()
            for lang in languages:
                local.add_language(LanguageModel(lang))
                
            local.update_movies_table()
            local.update_series_table()

            shared.schema.set_boolean('first-run', False)
            shared.schema.set_boolean('offline-mode', False)
            shared.schema.set_boolean('onboard-complete', True)
            shared.schema.set_boolean('db-needs-update', False)

            self._setup_languages()
            
            Gio.NetworkMonitor.get_default().connect(
                'network-changed', self._on_network_changed)
        else:
            logging.error('No network, aborting first setup completion')
            dialog = Adw.AlertDialog.new(
                heading=C_('message dialog heading', 'No Network'),
                body=C_('message dialog body', 'Connect to the Internet to complete the setup.')
            )
            dialog.add_response('ok', C_('alert dialog action', '_OK'))
            dialog.choose(self, None, None, None)

    def _on_network_changed(self, network_monitor: Gio.NetworkMonitor, network_available: bool) -> None:
        """
        Callback for "network-changed" signal.
        If no network is available, it turns on offline mode.

        Args:
            network_monitor (Gio.NetworkMonitor): the NetworkMonitor in use
            network_available (bool): whether or not the network is available

        Returns:
            None
        """

        shared.schema.set_boolean(
            'offline-mode', GLib.Variant.new_boolean(not network_available))

    @Gtk.Template.Callback('_on_clear_cache_activate')
    def _on_clear_cache_activate(self, user_data: object | None) -> None:
        """
        Callback for "activated" signal.
        Shows a confirmation dialog to the user.

        Args:
            user_data (object or None): additional data passed to the callback

        Returns:
            None
        """

        logging.debug('Show cache clear dialog')
        builder = Gtk.Builder.new_from_resource(
            shared.PREFIX + '/ui/dialogs/message_dialogs.ui')
        _clear_cache_dialog = builder.get_object('_clear_cache_dialog')
        _clear_cache_dialog.choose(self,
            None, self._on_cache_message_dialog_choose, None)

    def _on_cache_message_dialog_choose(self,
                                        source: GObject.Object | None,
                                        result: Gio.AsyncResult,
                                        user_data: object | None) -> None:
        """
        Callback for the message dialog.
        Finishes the async operation and retrieves the user response. If the later is positive, adds a background activity to delete the cache.

        Args:
            source (Gtk.Widget): object that started the async operation
            result (Gio.AsyncResult): a Gio.AsyncResult
            user_data (object or None): additional data passed to the callback

        Returns:
            None
        """

        result = Adw.AlertDialog.choose_finish(source, result)
        if result == 'cache_cancel':
            logging.debug('Cache clear dialog: cancel, aborting')
            return

        logging.debug('Cache clear dialog: sel, aborting')
        BackgroundQueue.add(
            activity=BackgroundActivity(
                activity_type=ActivityType.REMOVE,
                title=C_('Background activity title', 'Clear cache'),
                task_function=self._clear_cache),
            on_done=self._on_cache_clear_done)

    def _clear_cache(self, activity: BackgroundActivity) -> None:
        """
        Clears the cache.

        Args:
            activity (BackgroundActivity): the calling activity

        Returns:
            None
        """

        logging.info('Deleting cache')
        files = glob.glob('*.jpg', root_dir=shared.cache_dir)
        for file in files:
            os.remove(shared.cache_dir / file)
            logging.debug(f'Deleted {shared.cache_dir / file}')

    def _on_cache_clear_done(self,
                             source: GObject.Object,
                             result: Gio.AsyncResult,
                             cancellable: Gio.Cancellable,
                             activity: BackgroundActivity):
        self._update_occupied_space()
        activity.end()

    @Gtk.Template.Callback('_on_clear_activate')
    def _on_clear_btn_clicked(self, user_data: object | None) -> None:
        """
        Callback for "activated" signal.
        Shows a confirmation dialog to the user.

        Args:
            user_data (object or None): additional data passed to the callback

        Returns:
            None
        """

        logging.debug('Show data clear dialog')
        builder = Gtk.Builder.new_from_resource(
            shared.PREFIX + '/ui/dialogs/message_dialogs.ui')
        _clear_data_dialog = builder.get_object('_clear_data_dialog')
        _movies_row = builder.get_object('_movies_row')
        _series_row = builder.get_object('_series_row')
        self._movies_checkbtn = builder.get_object('_movies_checkbtn')
        self._series_checkbtn = builder.get_object('_series_checkbtn')

        # TRANSLATORS: {number} is the number of titles
        _movies_row.set_subtitle(_('{number} Titles').format(
            number=len(local.get_all_movies())))
        _series_row.set_subtitle(_('{number} Titles').format(
            number=len(local.get_all_series())))

        _clear_data_dialog.choose(self,
            None, self._on_data_message_dialog_choose, None)

    def _on_data_message_dialog_choose(self,
                                       source: GObject.Object | None,
                                       result: Gio.AsyncResult,
                                       user_data: object | None) -> None:
        """
        Callback for the message dialog.
        Finishes the async operation and retrieves the user response. If the later is positive, adds background activities to delete the selected data.

        Args:
            source (Gtk.Widget): object that started the async operation
            result (Gio.AsyncResult): a Gio.AsyncResultresult = Adw.AlertDialog.choose_finish(source, result)
        if result == 'data_cancel':
            return

            user_data (object or None): additional data passed to the callback

        Returns:
            None
        """

        result = Adw.AlertDialog.choose_finish(source, result)
        if result == 'data_cancel':
            logging.debug('Data clear dialog: cancel, aborting')
            return

        # Movies
        if self._movies_checkbtn.get_active():
            logging.debug('Data clear dialog: movies selected')
            BackgroundQueue.add(
                activity=BackgroundActivity(
                    activity_type=ActivityType.REMOVE,
                    title=C_('Background activity title', 'Delete all movies'),
                    task_function=self._clear_movies),
                on_done=self._on_data_clear_done)

        # TV Series
        if self._series_checkbtn.get_active():
            logging.debug('Data clear dialog: tv series selected')
            BackgroundQueue.add(
                activity=BackgroundActivity(
                    activity_type=ActivityType.REMOVE,
                    title=C_('Background activity title',
                             'Delete all TV Series'),
                    task_function=self._clear_series),
                on_done=self._on_data_clear_done)

    def _clear_movies(self, activity: BackgroundActivity) -> None:
        """
        Clears all movies.

        Args:
            activity (BackgroundActivity): the calling activity

        Returns:
            None
        """

        logging.info('Deleting all movies')
        for movie in local.get_all_movies():    # type: ignore
            local.delete_movie(movie.id)
            logging.debug(f'Deleted ({movie.id}) {movie.title}')

    def _on_data_clear_done(self,
                            source: GObject.Object,
                            result: Gio.AsyncResult,
                            cancellable: Gio.Cancellable,
                            activity: BackgroundActivity):
        """Callback to complete async activity"""

        self._update_occupied_space()
        self.get_parent().activate_action('win.refresh', None)
        activity.end()

    def _clear_series(self, activity: BackgroundActivity) -> None:
        """
        Clears all TV series.

        Args:
            activity (BackgroundActivity): the calling activity

        Returns:
            None
        """

        logging.info('Deleting all TV series')
        for serie in local.get_all_series():    # type: ignore
            local.delete_series(serie.id)
            logging.debug(f'Deleted ({serie.id}) {serie.title}')

    def _calculate_space(self, directory: Path) -> float:
        """
        Given a directory, calculates the total space occupied on disk.

        Args:
            directory (Path): the directory to measure

        Returns:
            float with space occupied in MegaBytes (MB)
        """

        return sum(file.stat().st_size for file in directory.rglob('*'))/1024.0/1024.0

    def _update_occupied_space(self) -> None:
        """
        After calculating space occupied by cache and data, updates the ui labels to reflect the values.

        Args:
            None

        Returns:
            None
        """

        cache_space = self._calculate_space(shared.cache_dir)
        data_space = self._calculate_space(shared.data_dir)

        self._housekeeping_group.set_description(  # TRANSLATORS: {total_space:.2f} is the total occupied space
            _('Ticket Booth is currently using {total_space:.2f} MB. Use the options below to free some space.').format(total_space=cache_space+data_space))

        # TRANSLATORS: {space:.2f} is the occupied space
        self._cache_row.set_subtitle(
            _('{space:.2f} MB occupied').format(space=cache_space))
        self._data_row.set_subtitle(
            _('{space:.2f} MB occupied').format(space=data_space))

    @Gtk.Template.Callback('_on_own_key_changed')
    def _on_own_key_changed(self, user_data: object | None) -> None:
        """
        Callback for 'changed' signal.
        Removes all CSS classes.

        Args:
            user_data (object or None): additional data passed to the callback

        Returns:
            None
        """

        self._own_key_entryrow.remove_css_class('error')
        self._own_key_entryrow.remove_css_class('success')

    @Gtk.Template.Callback('_on_check_own_key_button_clicked')
    def _on_check_own_key_button_clicked(self, user_data: object | None) -> None:
        """
        Callback for 'clicked' signal.
        Temporarelly changes the API key in use with the one provided and checks if it is valid.

        Args:
            user_data (object or None): additional data passed to the callback

        Returns:
            None
        """

        tmdb.set_key(self._own_key_entryrow.get_text())
        try:
            tmdb.get_movie(575264)
            shared.schema.set_string(
                'own-tmdb-key', self._own_key_entryrow.get_text())
            self._own_key_entryrow.add_css_class('success')
        except (tmdbsimple.base.APIKeyError, HTTPError):
            self._own_key_entryrow.add_css_class('error')
            tmdb.set_key(tmdb.get_builtin_key())

    def _on_use_own_key_switch_activated(self, pspec, user_data: object | None) -> None:
        """
        Callback for 'notify::active' signal.
        Sets the API key is use based on the state of the property.

        Args:
            pspec (GObject.ParamSpec): pspec of the changed property
            user_data (object or None): additional data passed to the callback

        Returns:
            None
        """

        if self._use_own_key_switch.get_active():
            tmdb.set_key(self._own_key_entryrow.get_text())
        else:
            tmdb.set_key(tmdb.get_builtin_key())

    
    @Gtk.Template.Callback('_tmdb_sync_row_activated')
    def _tmdb_sync_row_activated(self, user_data: object | None) -> None:
        """
        Open TMDB sync subpage.

        Args:
            None

        Returns:
            None
        """
        self.push_subpage(self._tmdb_setup_page)

    @Gtk.Template.Callback('_on_tmdb_close_btn_clicked')
    def _on_tmdb_close_btn_clicked(self, user_data: object | None) -> None:
        """
        Cancels sync if active, else closes TMDB sync subpage. 

        Args:
            None

        Returns:
            None
        """
        if self.tmdb_cancel:
            self.tmdb_cancel.cancel() # This is connected to self._tmdb_watchlist_sync_cancel()
            return
        self.pop_subpage()

    @Gtk.Template.Callback('_tmdb_sync_map')
    def _tmdb_sync_map(self, user_data: object | None) -> None:
        """
        Show different carousel page depending on the tmdb sync status

        Args:
            None

        Returns:
            None
        """
        index = shared.schema.get_int('tmdb-status')
        
        # If we are on the last step there is no continue button
        if index == 2:
            self._tmdb_continue_btn.set_visible(False)
        
        # Workaround to scroll to page
        task = Gio.Task.new()
        task.run_in_thread(
            lambda*_:self.go_to_page(index)
        )

    def go_to_page(self, index):
        """
        Helper function to scroll carousel to right page.

        Args:
            index: Page number to scroll to.

        Returns:
            None
        """
        sleep(0.05)
        page = self._tmdb_carousel.get_nth_page(index)
        self._tmdb_carousel.scroll_to(page, False)

    @Gtk.Template.Callback('_tmdb_link_clicked')
    def _tmdb_link_clicked(self, user_data: object | None) -> None:
        """
        Get request token and opens TMDB link to accept the request token

        Args:
           None

        Returns:
            None
        """
        token = tmdb.get_request_token()
        if token:
            self.request_token = token
            Gtk.UriLauncher(uri=f"https://www.themoviedb.org/authenticate/{token}").launch()
            self._tmdb_continue_btn.set_sensitive(True)
        else:
            toast = Adw.Toast(
                title=_("Error: Could not connect to TMDB. Are you online?"), 
                timeout=5)
            self.add_toast(toast)

    @Gtk.Template.Callback('_on_tmdb_continue_btn_clicked')
    def _on_tmdb_continue_btn_clicked(self, user_data: object | None) -> None:
        """
        Changes the page of the carousel if all the requirements are met, else it displays an Error Toast
        
        Args:
           None

        Returns:
            None
        """
        index = int(self._tmdb_carousel.get_position())
        if index == 0: 
            # Check if request token was confirmed 
            self.session_id = tmdb.get_session(self.request_token)
            if self.session_id == None:
                # Show Error Toast and return.
                toast = Adw.Toast(
                    title=_("Error: Could not connect to TMDB Account. Did you approve the request?"), 
                    timeout=5)
                self.add_toast(toast)
                return
            
            self.account = tmdb.make_account(self.session_id)
            #Check if account can be accessed, highly unlikely to fail right after get_session worked
            if self.account == None:
                toast = Adw.Toast(
                    title=_("Error: Could not connect to TMDB Account."), 
                    timeout=5)
                self.add_toast(toast)
                return

            shared.schema.set_int('tmdb-status', 1)

            next_page = self._tmdb_carousel.get_nth_page(index + 1)
            self._tmdb_carousel.scroll_to(next_page, True)
            
            self._tmdb_continue_btn.set_label(_("Start Sync"))

        elif index == 1:
            # Change appearance of back button back to cancel sync button
            self._tmdb_close_btn.remove_css_class("suggested-action")
            self._tmdb_close_btn.add_css_class("destructive-action")
            self._tmdb_close_btn.set_label(_("Cancel Sync"))

            #Show Spinner
            self._tmdb_spinner.set_visible(True)
            self._tmdb_radio_button_box.set_sensitive(False)

            # Do the watchlist sync asynchronous to make it cancellable
            self.tmdb_cancel = Gio.Cancellable.new()
            self.tmdb_cancel.connect(self._tmdb_watchlist_sync_cancel, None, None)
            self.tmdb_watchlist_task = Gio.Task.new(self, self.tmdb_cancel, self._tmdb_watchlist_sync_completed, None)
            self.tmdb_watchlist_task.run_in_thread(
                lambda*_:self._tmdb_watchlist_sync()
            )

    def _tmdb_watchlist_sync(self):
        """
        Starts the watchlist sync. 
        
        Args:
           None

        Returns:
            None
        """
        if self._keep_tmdb_check_btn.get_active():
            #delete both movies and series
            logging.info('Deleting all TV series')
            for serie in local.get_all_series():    # type: ignore
                local.delete_series(serie.id)
                logging.debug(f'Deleted ({serie.id}) {serie.title}')

            logging.info('Deleting all movies')
            for movie in local.get_all_movies():    # type: ignore
                local.delete_movie(movie.id)
                logging.debug(f'Deleted ({movie.id}) {movie.title}')

            local.add_tmdb_watchlist_to_local(self.account)
        elif self._keep_both_check_btn.get_active(): 
            local.merge_tmdb_watchlist(self.account)

        shared.schema.set_int('tmdb-status', 2)

    def _tmdb_watchlist_sync_completed(self, source: GObject.Object | None, result: Gio.AsyncResult, data: object | None):
        """
        Once the watchlist sync is completed change UI.

        Args:
           None

        Returns:
            None
        """
        
        self._tmdb_spinner.set_visible(False)
        self._tmdb_radio_button_box.set_sensitive(True)
        #Switch to last page
        next_page = self._tmdb_carousel.get_nth_page(2)
        self._tmdb_carousel.scroll_to(next_page, True)

        # Change appearance of back button back to normal back button
        self._tmdb_close_btn.remove_css_class("destructive-action")
        self._tmdb_close_btn.add_css_class("suggested-action")
        self._tmdb_close_btn.set_label(_("Go Back"))
        self.tmdb_cancel = None # No idea if this is needed or happens automatically
        
        #Remove continue button
        self._tmdb_continue_btn.set_visible(False)

    def _tmdb_watchlist_sync_cancel(self):
        """
        Callback if watchlist sync is cancelled

        Args:
           None

        Returns:
            None
        """
        self._tmdb_spinner.set_visible(False)
        self._tmdb_radio_button_box.set_sensitve(True)


    @Gtk.Template.Callback('_tmdb_logout_clicked')
    def _tmdb_logout_clicked(self, user_data: object | None) -> None:
        """
        Callback if logout button is clicked

        Args:
           None

        Returns:
            None
        """
        result = tmdb.delete_session()
        if result:
            shared.schema.set_string('tmdb-session-id', '')
            shared.schema.set_int('tmdb-status', 0)
            self._tmdb_continue_btn.set_visible(True)
            self._tmdb_continue_btn.set_sensitive(False)
            self._tmdb_continue_btn.set_label(_("Continue"))
            
            self.close_subpage()
        else: 
            toast = Adw.Toast(
                title=_("Error while logging out of your Account. Are you online?"), 
                timeout=5)
            self.add_toast(toast)
