-- Chinook: the sales database of an online music store (Chinook v1.4.5, MIT license; see LICENSE.md).
-- Sales run from 2009-01-01 to 2013-12-22. Money is in US dollars. Dates are 'YYYY-MM-DD HH:MM:SS'.
-- This annotated copy of the schema is what the model reads; the database itself is chinook.db.

CREATE TABLE Employee (
    EmployeeId  INTEGER PRIMARY KEY,
    LastName    TEXT NOT NULL,
    FirstName   TEXT NOT NULL,
    Title       TEXT,               -- job title, e.g. 'Sales Support Agent'
    ReportsTo   INTEGER REFERENCES Employee(EmployeeId),   -- the employee's manager
    BirthDate   DATETIME,
    HireDate    DATETIME,
    Address     TEXT,
    City        TEXT,
    State       TEXT,
    Country     TEXT,
    PostalCode  TEXT,
    Phone       TEXT,
    Fax         TEXT,
    Email       TEXT
);

CREATE TABLE Customer (
    CustomerId    INTEGER PRIMARY KEY,
    FirstName     TEXT NOT NULL,
    LastName      TEXT NOT NULL,
    Company       TEXT,             -- NULL for individual customers
    Address       TEXT,
    City          TEXT,
    State         TEXT,
    Country       TEXT,
    PostalCode    TEXT,
    Phone         TEXT,
    Fax           TEXT,
    Email         TEXT NOT NULL,
    SupportRepId  INTEGER REFERENCES Employee(EmployeeId)   -- the sales support agent assigned to the customer
);

-- One row per order. Total is the order's amount in USD (the sum of its invoice lines).
CREATE TABLE Invoice (
    InvoiceId          INTEGER PRIMARY KEY,
    CustomerId         INTEGER NOT NULL REFERENCES Customer(CustomerId),
    InvoiceDate        DATETIME NOT NULL,
    BillingAddress     TEXT,
    BillingCity        TEXT,
    BillingState       TEXT,
    BillingCountry     TEXT,
    BillingPostalCode  TEXT,
    Total              NUMERIC(10,2) NOT NULL
);

-- One row per track purchased on an invoice. Line amount = UnitPrice * Quantity.
CREATE TABLE InvoiceLine (
    InvoiceLineId  INTEGER PRIMARY KEY,
    InvoiceId      INTEGER NOT NULL REFERENCES Invoice(InvoiceId),
    TrackId        INTEGER NOT NULL REFERENCES Track(TrackId),
    UnitPrice      NUMERIC(10,2) NOT NULL,   -- price paid
    Quantity       INTEGER NOT NULL
);

-- The catalog of tracks for sale (songs, and some video episodes).
CREATE TABLE Track (
    TrackId       INTEGER PRIMARY KEY,
    Name          TEXT NOT NULL,
    AlbumId       INTEGER REFERENCES Album(AlbumId),
    MediaTypeId   INTEGER NOT NULL REFERENCES MediaType(MediaTypeId),
    GenreId       INTEGER REFERENCES Genre(GenreId),
    Composer      TEXT,             -- often NULL
    Milliseconds  INTEGER NOT NULL, -- length
    Bytes         INTEGER,          -- file size
    UnitPrice     NUMERIC(10,2) NOT NULL   -- current list price
);

CREATE TABLE Album (
    AlbumId   INTEGER PRIMARY KEY,
    Title     TEXT NOT NULL,
    ArtistId  INTEGER NOT NULL REFERENCES Artist(ArtistId)
);

CREATE TABLE Artist (
    ArtistId  INTEGER PRIMARY KEY,
    Name      TEXT
);

CREATE TABLE Genre (
    GenreId  INTEGER PRIMARY KEY,
    Name     TEXT
);

CREATE TABLE MediaType (
    MediaTypeId  INTEGER PRIMARY KEY,
    Name         TEXT              -- file format, e.g. 'MPEG audio file'
);

CREATE TABLE Playlist (
    PlaylistId  INTEGER PRIMARY KEY,
    Name        TEXT
);

CREATE TABLE PlaylistTrack (
    PlaylistId  INTEGER NOT NULL REFERENCES Playlist(PlaylistId),
    TrackId     INTEGER NOT NULL REFERENCES Track(TrackId),
    PRIMARY KEY (PlaylistId, TrackId)
);
