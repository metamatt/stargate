#! /bin/sh

# XXX this is leaving bogus Last-Modified and Content-Type headers
# above the xml output, even though we're not invoking curl with -i.
# Probably a Lutron HTTP server bug?
#
# So trim this manually with "tail +4".
curl http://lutron-radiora/DbXmlInfo.xml | tail +4 > RUN/DbXmlInfo.xml
