#! /bin/sh

# XXX this is leaving bogus Last-Modified and Content-Type headers
# above the xml output, even though we're not invoking curl with -i.
# This is because Lutron HTTP server writes \n\r\r after HTTP 200
# response line before additional headers, and \n\r between header
# lines, and \n\r\n after headers; this confuses curl into thinking
# the headers end too soon (and treat the header lines as part of
# the body).
#
# So trim this manually with "tail +4".
curl http://lutron-radiora/DbXmlInfo.xml | tail +4 > RUN/DbXmlInfo.xml
