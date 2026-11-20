-- M4F retains measured moving-line flag bits from real IBM Past QPU samples.
-- Older approved batches remain valid; NULL signifies flags were not captured.
ALTER TABLE ibm_inventory_items
  ADD COLUMN moving_qpu_bits TEXT
    CHECK(moving_qpu_bits IS NULL OR
          (length(moving_qpu_bits)=6 AND moving_qpu_bits NOT GLOB '*[^01]*'));
