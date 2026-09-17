#################### Imports ####################
import asyncio
import threading
import seaborn as sns
import sys
import signal

from idun_guardian_sdk import FileTypes, GuardianClient

# The star import also brings in numpy, deque and the PyQt6 names used below.
from front_end.EEGVisualizer import *


#################### Configuration ####################
####################   TO MODIFY   ####################
# Upper bound of the SDK-side recording, in seconds. Independent of the
# Start/Stop buttons, which only drive the local CSV recording.
RECORDING_TIMER = int(60 * 15)
LED_SLEEP = False

# IDUN credentials and BLE address of the device.
my_api_token = "idun_eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJqdGkiOiI4NDkxZDlmOC1kMGI2LTQ2Y2UtODI5Zi1hMWExMzNiYzFhNDIiLCJ1aWQiOiIyY2ExZmFlYS1kMDlkLTQ5ZTUtODMxYi1mNGE5YWNiNmEwNmUiLCJkaWQiOiJDQy0yNC00NS0yNi1FNy00RiIsImlhdCI6MTc3MDgyMDI1NS4xNzk3NzJ9.zdai6S6YTG56pXdbbQL0v3V5Hz8oK8j9RvoE7uMfrCE" 
device_address = "D5:65:DD:5C:37:CB"
device_connected = False

#############   END OF MODIFICATIONS   ################



################## Initialize variables and visualizer ###########
# Band keys expected in the SDK z-scores: used to build a complete dict when
# the SDK returns an empty list.
fft_keys = ['Delta', 'Theta', 'Alpha', 'Sigma', 'Beta', 'Gamma']

def shutdown():
    """
    Cancel all async tasks from the GUI thread. The loop is not stopped here:
    with no tasks left main() returns, and asyncio.run() with it.
    """
    global async_loop
    if async_loop and async_loop.is_running():
        async_loop.call_soon_threadsafe(_cancel_all_tasks)

def on_close():
    shutdown()
    if recording_thread:
        recording_thread.join(timeout=1)

app = QtWidgets.QApplication(sys.argv)
visualizer = EEGVisualizer(plot_FFT=True, on_close=on_close)
sns.set(style="whitegrid")


################### Handler functions ####################
def signal_handler(event):
    """
    Handler for the live insights stream (filtered EEG and IMU).

    Runs on the asyncio thread: the update goes through a Qt signal, which
    queues the slot on the thread owning the widget.
    """
    global visualizer

    data = event.message
    eeg_samples = [(sample['timestamp'], sample['ch1']) for sample in data['filtered_eeg']]
    #print(f"EEG values: {eeg_samples}")

    imu_data = data['imu']

    #visualizer.update_signals_visuals(eeg_samples, imu_data)
    visualizer.signal_update.emit(eeg_samples, imu_data)

                                
def pred_handler(event):
    """
    Handler for the realtime predictions.

    Each event carries a single predictionType, so exactly one branch below
    is taken per call and the remaining values keep their defaults. The
    QUALITY_SCORE branch paces the whole processing pipeline: its tick, at
    about 1 Hz, is what triggers the band power computation.
    """
    global visualizer

    jaw_clench = False
    heog_left = False
    heog_right = False
    fft_dict = {}
    quality_score = None
    timestamp = None

    if event.message["predictionType"] == "QUALITY_SCORE":
        quality_score = event.message["result"]['quality_score']

    if event.message["predictionType"] == "JAW_CLENCH":
        jaw_clench = True

    # Direction encoded in the sign: -1 left, +1 right.
    if event.message["predictionType"] == "BIN_HEOG":
        heog = event.message["result"]['heog']

        if heog == -1:
            heog_left = True

        if heog == 1:
            heog_right = True

    if event.message["predictionType"] == "FFT":
        timestamp = event.message["result"]["timestamp"]
        if len(event.message["result"]["z-scores"]) == 0:
            fft_dict = {key: None for key in fft_keys}
        else:
            fft_dict = event.message["result"]["z-scores"][0]

    #visualizer.update_predictions_visuals(quality_score, jaw_clench, heog_left, heog_right, fft_dict)
    visualizer.prediction_update.emit(quality_score, jaw_clench, heog_left, heog_right, (timestamp, fft_dict))
        

#################### Recording ####################
recording_done = False
async_loop = None
recording_thread = None

def _cancel_all_tasks():
    global async_loop
    tasks = asyncio.all_tasks(async_loop)
    for task in tasks:
        task.cancel()

async def do_recording(client):
    """
    Start the cloud recording and wait for RECORDING_TIMER to expire. The
    recording id is what fetches the full files from the IDUN API; those
    calls stay commented out because the analysis relies on the local CSVs.
    """

    await client.start_recording(recording_timer=RECORDING_TIMER, led_sleep=LED_SLEEP, calc_latency=False)

    rec_id = client.get_recording_id()
    print("RecordingId", rec_id)
    #client.update_recording_tags(recording_id=rec_id, tags=["tag1", "tag2"])
    #client.update_recording_display_name(recording_id=rec_id, display_name="todays_recordings")
    #client.download_file(recording_id=rec_id, file_type=FileTypes.EEG)

   

# The threshold is checked against the average of these values, not the last
# reading: electrode contact produces transients that a single sample would
# mistake for a good fit.
impedance_values = deque(maxlen=100)
async def main():
    global async_loop

    impedance_ok = asyncio.Event()
    def check_impedance(data):
        #print(f"{data}\tOhm")
        global device_connected
        if not device_connected:
            # There is no connection event: the first impedance reading is the
            # only hint that the BLE link is up.
            visualizer.device_connected_update.emit(True)
            device_connected = True
        impedance_values.append(data)
        if len(impedance_values) > 0:
            avg_impedance = np.mean(impedance_values)
            print(f"{avg_impedance}\tOhm")
            visualizer.impedance_update.emit(avg_impedance)
            if avg_impedance <= visualizer.IMPEDANCE_THRESHOLD:
                print(f"Impedance {avg_impedance} Ohm is below threshold, starting recording...")
                impedance_ok.set()    

    async_loop = asyncio.get_running_loop()
    client = GuardianClient(api_token=my_api_token, address=device_address)

    impedance_task = asyncio.create_task(client.stream_impedance(handler=check_impedance))
    try:
        await impedance_ok.wait()
    finally:
        impedance_task.cancel()
        try:
            await impedance_task
        except asyncio.CancelledError:
            pass

    client.subscribe_live_insights(raw_eeg=False, filtered_eeg=True, imu=True, handler=signal_handler)
    client.subscribe_realtime_predictions(jaw_clench=True, fft=True, bin_heog=True,quality_score=True, handler=pred_handler)

    try:
        await do_recording(client)
    except (asyncio.CancelledError):
        print("Recording cancelled, disconnecting...")
    finally:
        try:
            await client.disconnect_device()
        except asyncio.CancelledError:
            print("Disconnect interrupted by cancellation.")
        global recording_done
        recording_done = True

def check_for_completion():
    """
    Close the app once the SDK recording is over. Polling rather than a Qt
    signal: recording_done is set on the asyncio thread.
    """
    global app, visualizer
    if recording_done:
        visualizer.close()  
        app.quit()  
    else:
        QtCore.QTimer.singleShot(100, check_for_completion)


def handle_sigint(sig, frame):
    print("Ctrl+C detected from sigint, shutting down...")
    shutdown()
    if recording_thread:
        recording_thread.join(timeout=3)
    app.quit()

signal.signal(signal.SIGINT, handle_sigint)

#################### MAIN ##########################
if __name__ == "__main__":
    visualizer.show()

    # BLE, websocket and SDK callbacks run on a dedicated asyncio loop: the
    # main thread stays on the Qt event loop.
    recording_thread = threading.Thread(target=lambda: asyncio.run(main()), daemon=True)
    recording_thread.start()

    QtCore.QTimer.singleShot(100, check_for_completion)

    try:
        exit_code = app.exec()
    except KeyboardInterrupt:
        print("Ctrl+C detected, shutting down...")
        shutdown()
        recording_thread.join(timeout=3)
        exit_code = 0

    sys.exit(exit_code)