from flask_socketio import emit
import time
from module.redis_controller import ParameterKey

def register_events(socketio, redis_controller, cinepi_controller, simple_gui, sensor_detect):
    def camera_controls_available():
        return bool(getattr(sensor_detect, "res_modes", None))

    def _imu_push():
        import redis as _r
        rc=_r.Redis()
        last=None
        while True:
            try:
                d={'roll':float((rc.get('imu_roll') or b'0').decode() or 0),
                   'pitch':float((rc.get('imu_pitch') or b'0').decode() or 0),
                   'shake':float((rc.get('imu_shake') or b'0').decode() or 0)}
                if last is None or abs(d['roll']-last['roll'])>0.05 or abs(d['pitch']-last['pitch'])>0.05 or abs(d['shake']-last['shake'])>0.2:
                    socketio.emit('imu', d)
                    last=d
            except Exception:
                pass
            socketio.sleep(0.04)
    socketio.start_background_task(_imu_push)
    def resolution_switching_active():
        return str(
            redis_controller.get_value(ParameterKey.RESOLUTION_SWITCHING.value, "0")
            or "0"
        ).strip().lower() in ("1", "true", "yes", "on")

    def selected_resolution_mode():
        target_mode = redis_controller.get_value(ParameterKey.RESOLUTION_TARGET_MODE.value)
        if resolution_switching_active() and target_mode is not None:
            return target_mode
        return redis_controller.get_value(ParameterKey.SENSOR_MODE.value)

    def emit_resolution_selection(selected_mode=None):
        if not camera_controls_available():
            socketio.emit('parameter_change', {
                'selected_resolution_mode': None,
                'resolution_switching': "0",
            })
            return
        socketio.emit('parameter_change', {
            'selected_resolution_mode': (
                selected_mode
                if selected_mode is not None
                else selected_resolution_mode()
            ),
            'resolution_switching': redis_controller.get_value(
                ParameterKey.RESOLUTION_SWITCHING.value,
                "0",
            ),
        })
    
    @socketio.on('connect')
    def handle_connect():
        initial_values = {
            'iso': redis_controller.get_value(ParameterKey.ISO.value),
            'shutter_a': redis_controller.get_value(ParameterKey.SHUTTER_A.value),
            'fps': redis_controller.get_value(ParameterKey.FPS_ACTUAL.value),
            'background_color': simple_gui.get_background_color(),
            'recording': str(
                redis_controller.get_value(ParameterKey.IS_RECORDING.value, "0")
                or "0"
            ).strip().lower() in ("1", "true", "yes", "on"),
            'shutter_a_steps': cinepi_controller.shutter_a_steps_dynamic,
            'fps_steps': cinepi_controller.fps_steps_dynamic,
            'wb_steps': cinepi_controller.wb_steps,
            'wb': redis_controller.get_value(ParameterKey.WB_USER.value) or (cinepi_controller.wb_steps[0] if cinepi_controller.wb_steps else None)
        }

        initial_values.update(simple_gui.populate_values())

        camera_present = camera_controls_available()
        initial_values['sensor_resolutions'] = (
            sensor_detect.get_available_resolutions() if camera_present else []
        )
        initial_values['current_sensor'] = (
            sensor_detect.camera_model if camera_present else None
        )
        initial_values['camera_present'] = camera_present
        initial_values['selected_resolution_mode'] = (
            selected_resolution_mode() if camera_present else None
        )
        initial_values['resolution_switching'] = (
            redis_controller.get_value(
                ParameterKey.RESOLUTION_SWITCHING.value,
                "0",
            )
            if camera_present
            else "0"
        )
        if not camera_present:
            initial_values.update({
                'iso': None,
                'shutter_a': None,
                'fps': None,
                'wb': None,
                'shutter_a_steps': [],
                'fps_steps': [],
                'wb_steps': [],
            })

        emit('initial_values', initial_values)

    def redis_change_handler(data):
        key = data['key']
        value = data['value']
        camera_parameter_keys = {
            ParameterKey.ISO.value,
            ParameterKey.SHUTTER_A.value,
            ParameterKey.FPS_ACTUAL.value,
            ParameterKey.WB.value,
        }
        if key in camera_parameter_keys:
            if camera_controls_available():
                socketio.emit('parameter_change', {key: value})
        elif key in (ParameterKey.FRAMECOUNT.value, ParameterKey.BUFFER.value):
            socketio.emit('parameter_change', {key: value})

        if key == ParameterKey.IS_RECORDING.value:
            recording = str(value or "0").strip().lower() in (
                "1", "true", "yes", "on"
            )
            socketio.emit('recording_state', {
                'recording': recording,
                'timecode': redis_controller.get_value(
                    ParameterKey.RECORDING_TC_REC.value,
                    "00:00:00:00",
                ),
            })

        if key == ParameterKey.WB_USER.value and camera_controls_available():
            socketio.emit('parameter_change', {'wb': value})

        if key == ParameterKey.FPS_ACTUAL.value and camera_controls_available():
            # Emit the updated shutter_a_steps array and the current shutter speed
            shutter_a_steps = cinepi_controller.calculate_dynamic_shutter_angles(
                int(float(redis_controller.get_value(ParameterKey.FPS_ACTUAL.value)))
            )
            current_shutter_a = redis_controller.get_value(ParameterKey.SHUTTER_A.value)
            socketio.emit('shutter_a_update', {'shutter_a_steps': shutter_a_steps, 'current_shutter_a': current_shutter_a})

        if key == ParameterKey.RESOLUTION_TARGET_MODE.value:
            emit_resolution_selection(value)

        if key in (ParameterKey.SENSOR_MODE.value, ParameterKey.RESOLUTION_SWITCHING.value):
            emit_resolution_selection()

        if key == ParameterKey.WB.value and camera_controls_available():
            time.sleep(2)  # Add a 2-second pause
            socketio.emit('reload_browser')  # Emit event to reload the browser

    redis_controller.redis_parameter_changed.subscribe(redis_change_handler)

    @socketio.on('update_background_color')
    def handle_update_background_color():
        background_color = simple_gui.get_background_color()
        socketio.emit('background_color_change', {'background_color': background_color})

    @socketio.on('change_framebuffer')
    def handle_change_framebuffer(data):
        framebuffer = data.get('framebuffer')
        if framebuffer:
            socketio.emit('parameter_change', {'framebuffer': framebuffer})
            print(emit)

    @socketio.on('change_iso')
    def handle_change_iso(data):
        if not camera_controls_available():
            return
        iso = data.get('iso')
        if iso:
            cinepi_controller.set_iso(int(iso))
            socketio.emit('parameter_change', {'iso': iso})

    @socketio.on('change_shutter_a')
    def handle_change_shutter_a(data):
        if not camera_controls_available():
            return
        shutter_a = data.get('shutter_a')
        if shutter_a:
            cinepi_controller.set_shutter_a(float(shutter_a))
            socketio.emit('parameter_change', {'shutter_a': shutter_a})
            # Emit the updated shutter_a_steps array and the current shutter speed
            shutter_a_steps = cinepi_controller.calculate_dynamic_shutter_angles(
                int(float(redis_controller.get_value(ParameterKey.FPS_ACTUAL.value)))
            )
            socketio.emit('shutter_a_update', {'shutter_a_steps': shutter_a_steps, 'current_shutter_a': shutter_a})

    @socketio.on('change_fps')
    def handle_change_fps(data):
        if not camera_controls_available():
            return
        fps = data.get('fps')
        if fps:
            cinepi_controller.set_fps(int(fps))
            socketio.emit('parameter_change', {'fps': fps})
            # Emit the updated shutter_a_steps array and the current shutter speed
            shutter_a_steps = cinepi_controller.calculate_dynamic_shutter_angles(int(fps))
            current_shutter_a = redis_controller.get_value(ParameterKey.SHUTTER_A.value)
            socketio.emit('shutter_a_update', {'shutter_a_steps': shutter_a_steps, 'current_shutter_a': current_shutter_a})

    @socketio.on('change_wb')
    def handle_change_wb(data):
        if not camera_controls_available():
            return
        wb = data.get('wb')
        if wb:
            cinepi_controller.set_wb(int(wb))  # Call set_wb method
            socketio.emit('parameter_change', {'wb': wb})   

    @socketio.on('change_resolution')
    def handle_change_resolution(data):
        if not camera_controls_available():
            return
        sensor_mode = data.get('mode')
        if sensor_mode is not None:
            socketio.emit('parameter_change', {
                'selected_resolution_mode': sensor_mode,
                'resolution_switching': "1",
            })
            if not cinepi_controller.set_resolution(int(sensor_mode)):
                emit_resolution_selection()
                return
            # Emit the current values and steps immediately before reloading
            shutter_a_steps = cinepi_controller.calculate_dynamic_shutter_angles(
                int(float(redis_controller.get_value(ParameterKey.FPS_ACTUAL.value)))
            )
            current_shutter_a = redis_controller.get_value(ParameterKey.SHUTTER_A.value)
            current_fps = redis_controller.get_value(ParameterKey.FPS_ACTUAL.value)
            socketio.emit('shutter_a_update', {
                'shutter_a_steps': shutter_a_steps,
                'current_shutter_a': current_shutter_a
            })
            socketio.emit('fps_update', {
                'fps_steps': cinepi_controller.fps_steps_dynamic,
                'current_fps': current_fps
            })

            socketio.emit('reload_stream')

    @socketio.on('container_tap')
    def handle_container_tap():
        cinepi_controller.rec()
        
    @socketio.on('gui_data_change')
    def handle_gui_data_change(data):
        emit('gui_data_change', data)
        
    @socketio.on('unmount')
    def handle_unmount():
        cinepi_controller.unmount()
        socketio.emit('unmount_complete')
