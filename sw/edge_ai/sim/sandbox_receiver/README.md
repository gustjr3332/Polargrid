# Sandbox notification receiver

A tiny MEC app (Python 3.12 standard library only) for the ETSI MEC Sandbox, internal mode
(TR-0086 clause 5.4). It runs next to the ACME MN-CSE, registers an AE with a point of access (poa),
answers the subscription verification request, and stores every other notification as a CIN in
`<AE_RN>/received`, so the result can be read from outside with curl.

## Environment variables

| Variable | Default |
|---|---|
| `CSE_URL` | `http://mep1-meep-acme-mn-cse` (in-cluster MN-CSE, TR-0086 table 5.4.1-1) |
| `CSE_BASE` | `acme-cse-mn-<MEP>-<MEEP_SANDBOX_NAME>`; the sandbox injects `MEEP_SANDBOX_NAME`, `MEP` defaults to `mep1`. Exits if neither is set. |
| `APP_NAME` | `polagrid-rx` (must equal the element name given in the sandbox UI; used in the poa) |
| `PORT` | `8080` |
| `AE_RN` | `polagrid-sbxrx` |
| `ORIGINATOR` | `CPolaGridSbxRx` |

`GET /healthz` answers `ok`.

## Build

    ./docker_build.sh        # builds polagrid-rx:latest for linux/amd64; does not log in or push

Manual steps (TR-0086 clauses 5.4.3.2 and 5.4.3.3): push the image to a public Docker Hub repository,
then add the element in the sandbox UI with the same name as `APP_NAME`.

## Use

Create a subscription whose `nu` is the receiver's poa, then read the stored notifications:

    curl -k -X POST https://<sandbox-host>/<sandbox-id>/mep1/meep-acme-mn-cse/<csebase>/<target-resource> \
      -H 'X-M2M-Origin: <originator>' -H 'X-M2M-RI: sub1' -H 'X-M2M-RVI: 3' \
      -H 'Content-Type: application/json;ty=23' \
      -d '{"m2m:sub": {"rn": "rx-sub", "enc": {"net": [3]}, "nu": ["http://polagrid-rx:8080"]}}'

    curl -k https://<sandbox-host>/<sandbox-id>/mep1/meep-acme-mn-cse/<csebase>/polagrid-sbxrx/received/la \
      -H 'X-M2M-Origin: <originator>' -H 'X-M2M-RI: r1' -H 'X-M2M-RVI: 3' -H 'Accept: application/json'

Test without docker: `python -m pytest -q tests/test_sandbox_receiver.py` (from `sw/edge_ai`).
