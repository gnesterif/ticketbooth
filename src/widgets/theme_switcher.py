# Code modified from https://gitlab.gnome.org/tijder/blueprintgtk
# Original header below
# ---------------------
#
# Copyright 2020 Manuel Genovés
# Copyright 2022 Mufeed Ali
# Copyright 2022 Rafael Mardojai CM
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Code modified from Apostrophe
# https://github.com/dialect-app/dialect/blob/c0b7ca0580d4c7cfb32ff7ed0a3a08c06bbe40e0/dialect/theme_switcher.py

from gi.repository import Adw, Gdk, Gio, GObject, Gtk

from .. import shared  # type: ignore


@Gtk.Template(resource_path=shared.PREFIX + '/ui/widgets/theme_switcher.ui')
class ThemeSwitcher(Gtk.Box):
    __gtype_name__ = 'ThemeSwitcher'

    __gsignals__ = {
        'themer-clicked': (GObject.SIGNAL_RUN_FIRST, None, ()),
    } 

    show_system = GObject.property(type=bool, default=True)
    color_scheme = 'light'
   

    system = Gtk.Template.Child()
    light = Gtk.Template.Child()
    dark = Gtk.Template.Child()

    @GObject.Property(type=str)
    def selected_color_scheme(self):  # type: ignore
        """Read-write integer property."""

        return self.color_scheme

    @selected_color_scheme.setter
    def set_selected_color_scheme(self, color_scheme):
        self.color_scheme = color_scheme

        if color_scheme == 'auto':
            self.system.set_active(True)
            self.style_manager.set_color_scheme(Adw.ColorScheme.PREFER_LIGHT)
        if color_scheme == 'light':
            self.light.set_active(True)
            self.style_manager.set_color_scheme(Adw.ColorScheme.FORCE_LIGHT)
        if color_scheme == 'dark':
            self.dark.set_active(True)
            self.style_manager.set_color_scheme(Adw.ColorScheme.FORCE_DARK)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        self.style_manager = Adw.StyleManager.get_default()

        self.style_manager.bind_property(
            'system-supports-color-schemes',
            self, 'show_system',
            GObject.BindingFlags.SYNC_CREATE
        )

        self.selected_color_scheme = shared.schema.get_string('style-scheme')

    @Gtk.Template.Callback()
    def _on_color_scheme_changed(self, _widget, _paramspec):
        if self.system.get_active():
            self.selected_color_scheme = 'auto'  # type: ignore
            shared.schema.set_string('style-scheme', 'auto')
        if self.light.get_active():
            self.selected_color_scheme = 'light'  # type: ignore
            shared.schema.set_string('style-scheme', 'light')
        if self.dark.get_active():
            self.selected_color_scheme = 'dark'  # type: ignore
            shared.schema.set_string('style-scheme', 'dark')
        # emit signal so we can change the background of details page if needed
        self.emit('themer-clicked')
