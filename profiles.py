"""Document-specific suggestions; all require manual review."""
PROFILES = {
    'Paystub': ('Keep name, employer, pay dates, and income totals visible if required.',
                'Suggest SSN, bank/routing numbers, employee IDs, confidential client/project names and internal pricing. Keep name, employer, pay dates and gross/net/YTD income visible.'),
    'Bank statement': ('Keep holder, bank name, statement dates, balances, and amounts visible if required.',
                'Suggest full bank account/routing/IBAN/card numbers, SSN and customer IDs. Keep account holder, bank name, dates, balances, totals and transaction amounts visible. Do not hide transaction descriptions by default.'),
    "Driver's license / passport": ('ID preset suggests document numbers, MRZ, signatures and barcodes. Check recipient requirements.',
                'Suggest passport/license/document/personal ID numbers, handwritten signatures, barcodes, QR codes and passport machine-readable zones (MRZ). Keep name, photo, birth date, address, issuing authority and validity dates visible. MRZ/barcodes can encode those same details. For non-text regions use a descriptive label and approximate box.'),
    'Mixed / general': ('General suggestions cover identifiers. Review recipient requirements; add other boxes manually.',
                'Suggest SSN, bank/account/routing/card numbers, employee/customer IDs, passport/license/document numbers, signatures, barcodes and passport MRZ. Keep names, dates, photographs, income, balances and transaction amounts visible. Do not hide ordinary numbers or transaction descriptions.'),
}
COMMON = [(r'\b(?:ssn|social\s+security(?:\s+(?:number|no\.?))?)\s*[:#]?\s*(.+)', 'Social Security number')]
BANK = [
    (r'\b(?:bank\s+account|(?:account|acct\.?)\s*(?:number|no\.?|#)|routing\s*(?:number|no\.?|#)?)\s*[:#]?\s*(.+)', 'Bank details'),
    (r'\b(?:iban|swift|bic|(?:debit|credit|payment)\s+card\s*(?:number|no\.?|#)?)\s*[:#]?\s*(.+)', 'Bank identifier'),
    (r'\bcustomer\s*(?:id|number|no\.?|#)\s*[:#]?\s*(.+)', 'Customer identifier'),
    (r'\b(?:account|acct\.?)\s*:\s*(.+)', 'Bank account'),
]
PAYROLL = [
    (r'\bemployee\s*(?:id|number|no\.?|#)\s*[:#]?\s*(.+)', 'Employee identifier'),
    (r'\b(?:confidential\s+)?(?:client|customer|project)(?:\s+(?:name|code))?\s*:\s*(.+)', 'Business detail'),
    (r'\binternal\s+(?:deal\s+)?pricing\s*:\s*(.+)', 'Internal pricing'),
]
IDENTITY = [
    (r"\b(?:(?:passport|document|licen[cs]e|driver['â€™]?s?\s+licen[cs]e|dl|id)\s*(?:number|no\.?|#)|dln|dd|4d)\s*[:#]?\s*(.+)", 'Identity document number'),
    (r'\bpersonal\s*(?:number|no\.?|#|id)\s*[:#]?\s*(.+)', 'Personal identifier'),
    (r'\b(?:dl|id)\s*:\s*(.+)', 'Identity document number'),
]
def patterns(profile):
    if profile == 'Paystub': return COMMON+BANK[:1]+PAYROLL
    if profile == 'Bank statement': return COMMON+BANK
    if profile == "Driver's license / passport": return COMMON+IDENTITY
    return COMMON+BANK+PAYROLL+IDENTITY
