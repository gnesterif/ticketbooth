# Copyright (C) 2023 Alessandro Iepure
#
# SPDX-License-Identifier: GPL-3.0-or-later

from gi.repository import Gio, GObject, Gtk
from PIL import Image, ImageStat
from pathlib import Path
from .. import shared  # type: ignore
from ..models.movie_model import MovieModel
from ..models.series_model import SeriesModel


@Gtk.Template(resource_path=shared.PREFIX + '/ui/widgets/poster_button.ui')
class PosterButton(Gtk.Box):
    """
    Widget shown in the main view with poster, title, and release year.

    Properties:
        title (str): content's title
        year (str): content's release year
        tmdb_id (str): content's tmdb id
        poster_path (str): content's poster uri

    Methods:
        None

    Signals:
        clicked(content: MovieModel or SeriesModel): emited when the user clicks on the widget
    """

    __gtype_name__ = 'PosterButton'

    _picture = Gtk.Template.Child()
    _spinner = Gtk.Template.Child()
    _year_lbl = Gtk.Template.Child()
    _status_lbl = Gtk.Template.Child()
    _watched_lbl = Gtk.Template.Child()
    _new_release_badge = Gtk.Template.Child()
    _soon_release_badge = Gtk.Template.Child()
    _watched_badge = Gtk.Template.Child()


    # Properties
    title = GObject.Property(type=str, default='')
    year = GObject.Property(type=str, default='')
    status = GObject.Property(type=str, default='')
    tmdb_id = GObject.Property(type=str, default='')
    poster_path = GObject.Property(type=str, default='')
    watched = GObject.Property(type=bool, default=False)
    content = GObject.Property(type=object, default=None)

    __gsignals__ = {
        'clicked': (GObject.SIGNAL_RUN_FIRST, None, (object,)),
    }

    def __init__(self, content: MovieModel | SeriesModel):
        super().__init__()
        self.title = content.title
        self.year = content.release_date[0:4]
        self.tmdb_id = content.id
        self.poster_path = content.poster_path
        self.watched = content.watched
        self.status = content.status
        if type(content) is SeriesModel:
            self.new_release = content.new_release
            self.soon_release = content.soon_release
        self.content = content

    @Gtk.Template.Callback('_on_map')
    def _on_map(self, user_data: object | None) -> None:
        """
        Callback for the 'map' signal.
        Sets images and hides release year label if not present.

        Args:
            user_data (object or None): data passed to the callback

        Returns:
            None
        """



        badge_color_light = 0
        if len(self.poster_path) > 0:
            path = Path(self.poster_path[7:])
            im = Image.open(path)
            box = (im.size[0]-175, 0, im.size[0], 175)
            region = im.crop(box)
            median = ImageStat.Stat(region).median
            if sum(median) < 3 * 128:
                badge_color_light = 1


        self._picture.set_file(Gio.File.new_for_uri(self.poster_path))
        self._spinner.set_visible(False)

        if type(self.content) is SeriesModel:
            if self.new_release:
                self._new_release_badge.set_visible(True)
                if badge_color_light:
                    self._new_release_badge.add_css_class("light")
                else:
                    self._new_release_badge.add_css_class("dark")
            elif self.soon_release:
                self._soon_release_badge.set_visible(True)
                if badge_color_light:
                    self._soon_release_badge.add_css_class("light")
                else:
                    self._soon_release_badge.add_css_class("dark")

            
        if not self.year:
            self._year_lbl.set_visible(False)
        if self.status == '':
            self._status_lbl.set_visible(False)
        if self.watched:
            self._watched_badge.set_visible(True)
            if badge_color_light:
                self._watched_badge.add_css_class("light")
            else:
                self._watched_badge.add_css_class("dark")

    @Gtk.Template.Callback('_on_poster_btn_clicked')
    def _on_poster_btn_clicked(self, user_data: object | None) -> None:
        self.emit('clicked', self.content)
