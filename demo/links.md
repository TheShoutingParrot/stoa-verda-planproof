# Demo links

Start `python3 server.py` with the sponsor ZIP at its default path. Each link opens a drawing the current reader had never seen in development and replays its sealed answer, with no model or key. Click the evidence rows to locate each mark on the original scan.

| Question | Drawing | Expected | Previous reader | Current reader |
|---|---|---:|---:|---:|
| Windows | [high_quality_architectural-6549](http://127.0.0.1:4179/scan-drawing.html?path=data%2Fcubicasa5k%2Fhigh_quality_architectural-6549.png&question=How+many+windows+are+shown+on+this+floor+plan%3F) | 18 | 15 | 18 |
| Windows | [high_quality_architectural-3580](http://127.0.0.1:4179/scan-drawing.html?path=data%2Fcubicasa5k%2Fhigh_quality_architectural-3580.png&question=How+many+windows+are+shown+on+this+floor+plan%3F) | 10 | 8 | 10 |
| Doors | [high_quality_architectural-1116](http://127.0.0.1:4179/scan-drawing.html?path=data%2Fcubicasa5k%2Fhigh_quality_architectural-1116.png&question=How+many+doors+are+shown+on+this+floor+plan%3F+Count+doorways+fitted+with+a+door%3B+open+doorways+without+a+door+leaf+do+not+count.) | 18 | 16 | 18 |
| Doors | [high_quality-8816](http://127.0.0.1:4179/scan-drawing.html?path=data%2Fcubicasa5k%2Fhigh_quality-8816.png&question=How+many+doors+are+shown+on+this+floor+plan%3F+Count+doorways+fitted+with+a+door%3B+open+doorways+without+a+door+leaf+do+not+count.) | 14 | 10 | 14 |
| Storeys | [high_quality-1692](http://127.0.0.1:4179/scan-drawing.html?path=data%2Fcubicasa5k%2Fhigh_quality-1692.png&question=How+many+floors+%28storeys%29+does+this+floor+plan+show%3F) | 3 | deferred | 3 |
| Storeys | [high_quality-19](http://127.0.0.1:4179/scan-drawing.html?path=data%2Fcubicasa5k%2Fhigh_quality-19.png&question=How+many+floors+%28storeys%29+does+this+floor+plan+show%3F) | 2 | deferred | 2 |
| Kitchens | [high_quality-1140](http://127.0.0.1:4179/scan-drawing.html?path=data%2Fcubicasa5k%2Fhigh_quality-1140.png&question=How+many+kitchens+%28including+kitchenettes%2C+open+kitchens+and+utility+kitchens%29+are+on+this+floor+plan%3F) | 1 | deferred | 1 |
| Kitchens | [high_quality-1692](http://127.0.0.1:4179/scan-drawing.html?path=data%2Fcubicasa5k%2Fhigh_quality-1692.png&question=How+many+kitchens+%28including+kitchenettes%2C+open+kitchens+and+utility+kitchens%29+are+on+this+floor+plan%3F) | 1 | deferred | 1 |
| Saunas | [high_quality-1140](http://127.0.0.1:4179/scan-drawing.html?path=data%2Fcubicasa5k%2Fhigh_quality-1140.png&question=How+many+saunas+are+on+this+floor+plan%3F) | 1 | deferred | 1 |
| Saunas | [high_quality-1692](http://127.0.0.1:4179/scan-drawing.html?path=data%2Fcubicasa5k%2Fhigh_quality-1692.png&question=How+many+saunas+are+on+this+floor+plan%3F) | 1 | deferred | 1 |
| Separate WC rooms | [high_quality_architectural-1701](http://127.0.0.1:4179/scan-drawing.html?path=data%2Fcubicasa5k%2Fhigh_quality_architectural-1701.png&question=How+many+separate+WC+rooms+%28toilet+rooms+marked+WC%29+are+on+this+floor+plan%3F) | 1 | deferred | 1 |
| Separate WC rooms | [high_quality_architectural-3984](http://127.0.0.1:4179/scan-drawing.html?path=data%2Fcubicasa5k%2Fhigh_quality_architectural-3984.png&question=How+many+separate+WC+rooms+%28toilet+rooms+marked+WC%29+are+on+this+floor+plan%3F) | 1 | deferred | 1 |
| Bathrooms | [high_quality_architectural-1601](http://127.0.0.1:4179/scan-drawing.html?path=data%2Fcubicasa5k%2Fhigh_quality_architectural-1601.png&question=How+many+bathrooms+or+washrooms+%28e.g.+KH%2C+KPH%2C+PH%2C+PESUH%2C+SH%29+are+on+this+floor+plan%2C+not+counting+separate+WC+rooms%3F) | 1 | deferred | 1 |
| Bathrooms | [high_quality_architectural-1652](http://127.0.0.1:4179/scan-drawing.html?path=data%2Fcubicasa5k%2Fhigh_quality_architectural-1652.png&question=How+many+bathrooms+or+washrooms+%28e.g.+KH%2C+KPH%2C+PH%2C+PESUH%2C+SH%29+are+on+this+floor+plan%2C+not+counting+separate+WC+rooms%3F) | 1 | deferred | 1 |
| Balconies | [high_quality_architectural-1652](http://127.0.0.1:4179/scan-drawing.html?path=data%2Fcubicasa5k%2Fhigh_quality_architectural-1652.png&question=How+many+balconies+%28parveke%2C+including+glazed+balconies%29+are+on+this+floor+plan%3F) | 0 | deferred | 0 |
| Balconies | [high_quality_architectural-541](http://127.0.0.1:4179/scan-drawing.html?path=data%2Fcubicasa5k%2Fhigh_quality_architectural-541.png&question=How+many+balconies+%28parveke%2C+including+glazed+balconies%29+are+on+this+floor+plan%3F) | 0 | deferred | 0 |

Live questions, with the detector Python (`.local/scan-dev/objects/venv/bin/python server.py`): type a count question and press **Run count**. With `NEMOTRON_BASE_URL=https://integrate.api.nvidia.com/v1` and the key in the server environment, questions no local reader can verify, such as showers, go to Nemotron 3.5 Super VL on NVIDIA's endpoint.
