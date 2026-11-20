-- Mutable subjective feedback, deliberately outside committed readings and research facts.
CREATE TABLE reading_resonance (
    consultation_id TEXT PRIMARY KEY REFERENCES reading_results(consultation_id) ON DELETE CASCADE,
    resonated INTEGER NOT NULL CHECK(resonated IN (0,1)),
    first_marked_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
