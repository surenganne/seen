"""What the PII detectors cover, stated wherever a result is shown."""

PII_CHECKED = ("Structured identifiers (email, phone, Aadhaar, PAN, card, IBAN, SSN, UPI, DOB, GSTIN, passport, secrets) in the "
               "prompt, file reads, tool and MCP output, network tool inputs and added diff lines. "
               "Names, addresses and free-text health details are not detected.")
