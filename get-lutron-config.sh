#! /bin/sh

curl http://lutron-radiora/DbXmlInfo.xml > lutron-DbXmlInfo.xml

# I've seen the file downloaded from the repeater be full of garbage
# for several reasons, including improperly bracketed tags, garbage
# characters inside name fields, and random truncation. When this
# happened, a repeater reboot fixed it. Sanity check for this condition
# by running xmllint. Ignore its stdout (which should be the same as
# the input), but anything on stderr means you should be wary.

xmllint lutron-DbXmlInfo.xml > /dev/null
