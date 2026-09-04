"""
Exact one-time staging market purge snapshot.

Generated from the verified 46-market staging state on
2026-08-18.

The original audited 40 rows remain unchanged;
six subsequently created non-canonical staging markets
were independently catalogue-audited and added to PURGE_IDS.

Never replace these UUIDs with a dynamic
"all markets except keepers" query.
"""

SNAPSHOT_VERSION = "2026-08-18-final-four-market-purge-v2"

SOURCE_TOTAL_MARKETS = 46

# SHA-256 over version, source total, sorted keepers
# and sorted purge UUIDs using the canonical payload
# described by the snapshot-generation script.
SNAPSHOT_DIGEST = "5cf21551d77a8e2edc76d3d1d04e581c8f74257c0cd7458875ae643e022ab175"

KEEPER_IDS = (
    "77d428eb-4f2d-41ce-981e-018bc59173f8",
    "7eb37016-e68e-4493-8c3f-41703d15c280",
    "a1374ce4-03fb-42f8-b545-a15a690587f0",
    "e118cded-bfd6-43db-9c25-6ecbc33e63b3",
)

PURGE_IDS = (
    "03e5cb25-a4ab-4036-af01-41a1c0af7d02",
    "0b2b4642-e357-43c8-b416-d94d87e774f5",
    "10eeaeb1-2ee6-456d-b23b-1c6b0a2b1928",
    "1a580f59-5b07-4781-b04d-a091f2ad3ffb",
    "208ddaa2-90bc-42c0-91f2-b50ff67d3ac9",
    "20e0b964-85bb-4cad-99d0-1163d8b9fcc5",
    "2321077a-3044-4dfe-8a37-d0a342f9e302",
    "2c7333ba-0da2-4a28-b829-ea7299b60b19",
    "3703ee48-1ade-4d20-ae26-40610a5651c2",
    "37472472-bf74-4e3c-bb72-34a8b4e2d426",
    "3fc403c6-d28e-4370-b1c8-e1e772e6608a",
    "47359490-416f-40df-9333-002f7e9acaf7",
    "5b506456-4bfe-4aee-91c6-2cfaef32de43",
    "5d9101ff-e143-422e-b4be-fef7c510f55a",
    "5e89d695-0d35-420c-a196-87b38de15044",
    "637e871d-e9bb-48a4-bd38-f77925f86ae7",
    "65490fec-b369-44d8-b6df-3f2cb78724e7",
    "655760e8-6116-4c18-91e5-f52def8c8e50",
    "7699c17f-3713-4f03-a65c-a1acb230601f",
    "81130dcb-118b-4764-b0e6-16ed5b88e1cb",
    "83470a02-5c2f-4d45-8145-fe695d5b938b",
    "859c23fe-945b-4b9c-859e-43ed93f40107",
    "872e09c6-643b-47e3-8b13-7d96c910b9d2",
    "8a9e35d6-211b-467c-9898-cc9a7541e49b",
    "8c6892dc-6761-407a-8129-f015a637101a",
    "8e51ff7e-e886-44b2-8907-a32ebe69c5f2",
    "8e8b92ba-e12a-4cfb-b932-16c858e6b96d",
    "903721cd-44ea-4fad-8848-0c80a94a1d39",
    "9a53e2df-57ac-447b-96c4-69eb828c3043",
    "9af89b57-486d-4baa-b0e3-4ad57dcb7248",
    "9e2fc428-6c8f-49ed-a76a-1cd1d7fda47d",
    "9ffcfdf8-342a-41fc-bf9e-10df74279c7c",
    "aef75655-b539-45cb-8593-a2ffc64d5668",
    "bbad0b8c-9ef7-4c15-8c27-638478fb3161",
    "e5c3dd27-8ea0-46b7-b44f-38eb88eb86d3",
    "e5e428d6-9707-4f83-ad7d-1efdcebb0911",
    "e95b6634-3d70-4803-81cb-297ad3fbb1bc",
    "efba3a1d-fa35-4de0-97ac-c0717c8a159a",
    "efeeb9bd-cb70-4f12-bed0-1c9bb056edcc",
    "f2fe2517-1be7-40cb-bc62-bdceb4b44cce",
    "fc93698a-aa63-4455-8910-9d62ac4b8834",
    "fd989f3d-4316-4c1e-8950-4f7e84d100f3",
)
