Stargate home automation controller
===================================

What
----

Stargate is a web interface to various home automation gateways including

* Lutron's RadioRa2 lighting/windowshade/HVAC home control system
  (Lutron's more capable Homeworks system has a similar network API and would
  probably mostly work with this code too, but it hasn't been tested.)
* DSC PowerSeries security system (via Eyez-On Envisalink ethernet integration
  interface)
* MiCasaVerde Vera home controller and Z-Wave gateway

Why
---

These devices present a variety of existing interfaces, including

* Physical control devices
* Mobile device (iOS, Android) applications
* Web user interface
* Network API or "third-party integration" API

Having used these devices in my own house, I found the available interfaces
deficient for one or more of the following reasons:

* Not being available for various devices (some are iOS only and not available
  for normal computers; some are web only and don't play well with touch
  devices)
* Available user interfaces don't export all features actually supported by
  the underlying hardware
* Needing to use a bunch of different apps or interfaces to access common tasks
* Network interface has silly limits, like only allowing one client at a time

I also wanted to add higher-level functionality such as

* Cross-device task automation (allowing control surfaces on one device to
  affect devices controlled by another device)
* Device usage and adjustment history
* Show me everything that's on, and turn it off with one click

Installing/Using
----------------

This is intended for hackers, for now anyway. There's no easy installation
process, and you need to be familiar with Python and the terminal environment.

Loosely, the steps are:

* Obtain Stargate source code from this repository.
* Obtain a compatible Python runtime. I recommend running Stargate from inside
  virtualenv; if you don't already have pip and virtualenv installed, install
  them and create a virtualenv for Stargate.
* Install dependencies. The get-dependencies.sh script will help you with this.
* Craft a config file (config.yaml). The config-example.yaml will help you with
  this. You may want to consult the Yaml documentation.
* If you're using a Lutron RadioRa2 repeater, Stargate knows how to obtain the
  configuration manifest from the repeater at startup, but I found this to be
  fragile and slow, so it also knows how to read a cached version of the
  configuration manifest. The get-lutron-config.sh script will help you with
  this.
* Invoke Stargate on the config file.
* Fix anything that went wrong.

Hacking
-------

Stargate is built as a collection of "gateway plugins" that talk to the various
home-automation control interface devices. (Yes, that last phrase is a mouthful,
which is why I introduced the term "gateway" to refer to that concept.) I only
implemented plugins for the gateways I own. It shouldn't be hard to extend these
gateways for similar devices, or add new ones.

The "synther" gateway plugin is a collection of hacks I use in my house to
extend and combine functionality beyond what's built in to the hardware. The
current implementation is pretty specific to what I needed it to do for me,
but it gives an idea of what's possible.

Thanks/Credits
--------------

Python, Flask (and Werkzeug, Jinja and friends), SQlite, Yaml, and the Internet
are excellent technologies. There are others, but these are what Stargate
depends on so far.

It's nice each of these home automation gateways presents some kind of network
integration interface, which means you aren't limited by what it can do out of
the box, and each one doesn't have to be the be-all-end-all of home automation.
That's what makes Stargate possible.
