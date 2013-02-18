#! /bin/sh

# Curl is leaving bogus Last-Modified and Content-Type headers
# above the xml output, even though we're not invoking curl with -i.
#
# This is because Lutron HTTP server writes \n\r\r after HTTP 200
# response line before additional headers, and \n\r between header
# lines, and \n\r\n after headers; this confuses curl into thinking
# the headers end too soon (thus treating the header lines as part of
# the body).
#
# So trim this manually with "tail +4".

curl http://lutron-radiora/DbXmlInfo.xml | tail +4 > lutron-DbXmlInfo.xml

# I've seen the file downloaded from the repeater be full of garbage
# for several reasons, including improperly bracketed tags, garbage
# characters inside name fields, and random truncation. When this
# happened, a repeater reboot fixed it. Sanity check for this condition
# by running xmllint. Ignore its stdout (which should be the same as
# the input), but anything on stderr means you should be wary.

xmllint lutron-DbXmlInfo.xml > /dev/null
