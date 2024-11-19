from pythermalcomfort.models import pmv
from pythermalcomfort.utilities import v_relative
import numpy as np
from asciimatics.screen import Screen
from asciimatics.exceptions import ResizeScreenError
from asciimatics.widgets import Frame, Layout, Label, TextBox, Text, Button, Divider
from asciimatics.scene import Scene
import sys
import csv
import os
from datetime import datetime

def find_air_velocity_and_ac_temp(desired_temp, outdoor_temp, outdoor_humidity, met, clo, init_ac_temp=28.0):
    # Constants
    pmv_baseline_temp = 24.0  # Reference temperature for PMV = 0
    pmv_temp_sensitivity = 0.3  # Change in PMV per degree C
    comfort_pmv = 0  # The target PMV value for user comfort

    # Calculate target PMV based on the user's desired temperature
    target_pmv = (desired_temp - pmv_baseline_temp) * pmv_temp_sensitivity

    rh = outdoor_humidity  # Use outdoor humidity to approximate indoor conditions

    # Create a lookup table of possible (air velocity, AC temperature) combinations
    ac_temp_range = np.arange(init_ac_temp, desired_temp + 0.5, -0.5)  # AC temperature from init_ac_temp to 4 degrees lower
    air_velocity_range = np.arange(0.1, 3.3, 0.1)  # Air velocity from 0.1 m/s to 3.2 m/s in increments of 0.1 m/s

    lookup_table = []  # Store all combinations for inspection
    best_ac_temp = None
    best_air_velocity = None
    closest_pmv = float('inf')

    # Search through all combinations to find the best match for the target PMV
    for air_velocity in reversed(air_velocity_range):
        for ac_temp in ac_temp_range:
            pmv_value = pmv(tdb=ac_temp, tr=ac_temp, vr=air_velocity, rh=rh, met=met, clo=clo)
            lookup_table.append((ac_temp, air_velocity, pmv_value))

            # Check if this PMV value is closer to the target PMV
            if abs(pmv_value - target_pmv) < abs(closest_pmv - target_pmv):
                best_ac_temp = ac_temp
                best_air_velocity = air_velocity
                closest_pmv = pmv_value

    # Save the lookup table to a CSV file
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"lookup_table_{timestamp}_temp{desired_temp}_humidity{outdoor_humidity}.csv"
    filepath = os.path.join(os.getcwd(), filename)
    with open(filepath, mode='w', newline='') as file:
        writer = csv.writer(file)
        writer.writerow(["AC Temperature (°C)", "Air Velocity (m/s)", "PMV"])
        writer.writerows(lookup_table)
    print(f"Lookup table saved to {filepath}")

    return best_air_velocity, best_ac_temp, closest_pmv, lookup_table

def calculate_fan_velocity(rpm: float, diameter: float = 1.2, air_delivery: float = 217) -> float:
    """
    Calculate air velocity below a ceiling fan
    
    Args:
        rpm: Fan speed in revolutions per minute
        diameter: Fan sweep diameter in meters (default 1.2m / 48 inches)
        air_delivery: Air delivery in cubic meters per minute (default 217 m³/min)
        
    Returns:
        Air velocity in meters/second
    """
    # Step 1: Calculate the area swept by the fan
    area = 3.14159 * (diameter / 2) ** 2  # Area in m²
    
    # Step 2: Convert air delivery to cubic meters per second
    air_delivery_m3s = air_delivery / 60  # Air delivery in m³/s

    # Step 3: Calculate air velocity
    velocity = air_delivery_m3s / area  # Velocity in m/s
    
    return velocity

def map_air_velocity_to_rpm(velocity: float) -> tuple:
    """
    Map the desired air velocity to the appropriate fan RPM setting, preferring middle range air velocity
    
    Args:
        velocity: Desired air velocity in meters per second
    
    Returns:
        Tuple of (selected_rpm, selected_speed)
    """
    fan_data = {
        120: {'air_delivery': 100},
        165: {'air_delivery': 130},
        210: {'air_delivery': 160},
        250: {'air_delivery': 190},
        295: {'air_delivery': 210},
        335: {'air_delivery': 217}
    }
    speed_mapping = {120: 1, 165: 2, 210: 3, 250: 4, 295: 5, 335: 6}

    diameter = 1.2  # Fan sweep diameter in meters
    selected_rpm = None
    selected_speed = None

    # Prefer middle range air velocity (speeds 3 or 4)
    preferred_rpm_range = [210, 250, 165, 295, 120, 335]

    for rpm in preferred_rpm_range:
        data = fan_data[rpm]
        air_velocity = calculate_fan_velocity(rpm, diameter, data['air_delivery'])
        if air_velocity is not None and air_velocity >= velocity:
            selected_rpm = rpm
            selected_speed = speed_mapping[rpm]
            break

    return selected_rpm, selected_speed

def heart_rate_to_met(heart_rate: float) -> float:
    """
    Convert heart rate to metabolic rate (met)
    
    Args:
        heart_rate: Heart rate in beats per minute
    
    Returns:
        Metabolic rate in met units
    """
    # This is a simple approximation for converting heart rate to met
    if heart_rate < 60:
        return 1.0  # Resting state
    elif heart_rate < 100:
        return 1.5  # Light activity
    elif heart_rate < 140:
        return 2.0  # Moderate activity
    else:
        return 3.0  # Heavy activity

def clothing_insulation_mapping(clothing_type: str) -> float:
    """
    Map clothing type to clo value based on ASHRAE 55 standards
    
    Args:
        clothing_type: Description of clothing (e.g., "summer clothing", "light blanket", etc.)
    
    Returns:
        Clo value for the given clothing type
    """
    clothing_map = {
        "summer clothing": 0.5,
        "winter clothing": 1.0,
        "light blanket": 0.7,
        "heavy blanket": 1.5,
        "shirt and trousers": 0.6,
        "sweater and trousers": 1.2
    }
    return clothing_map.get(clothing_type.lower(), 0.5)  # Default to summer clothing if not found

class ComfortApp(Frame):
    def __init__(self, screen):
        super(ComfortApp, self).__init__(screen, screen.height, screen.width, has_border=True, name="ComfortApp")
        # Layout for input fields
        layout = Layout([100], fill_frame=True)
        self.add_layout(layout)
        layout.add_widget(Label("SRI-B Efficient AI Cooling: UX Inputs", align="^"))
        layout.add_widget(Divider())
        self.desired_temp = Text("Desired feel-like temperature (°C): ", "desired_temp")
        self.outdoor_temp = Text("Outdoor temperature (°C): ", "outdoor_temp")
        self.outdoor_humidity = Text("Outdoor humidity (%): ", "outdoor_humidity")
        self.heart_rate = Text("Heart rate (bpm): ", "heart_rate")
        from asciimatics.widgets import DropdownList
        
        clothing_options = [
            ("Summer Clothing", "summer clothing"),
            ("Winter Clothing", "winter clothing"),
            ("Light Blanket", "light blanket"),
            ("Heavy Blanket", "heavy blanket"),
            ("Shirt and Trousers", "shirt and trousers"),
            ("Sweater and Trousers", "sweater and trousers")
        ]
        self.clothing_type = DropdownList(clothing_options, label="Clothing type: ")
        layout.add_widget(self.desired_temp)
        layout.add_widget(self.outdoor_temp)
        layout.add_widget(self.outdoor_humidity)
        layout.add_widget(self.heart_rate)
        layout.add_widget(self.clothing_type)
        layout.add_widget(Divider())
        layout.add_widget(Button("Calculate Comfort Settings", self._calculate))
        layout.add_widget(Divider())
        self.result_box = TextBox(10, "", "results", as_string=True, readonly=True)
        layout.add_widget(self.result_box)
        layout.add_widget(Divider())
        layout.add_widget(Label("Fan RPM and Speed Setting Mapping:", align="<"))
        layout.add_widget(Label("Speed 1: 120 RPM\nSpeed 2: 165 RPM\nSpeed 3: 210 RPM\nSpeed 4: 250 RPM\nSpeed 5: 295 RPM\nSpeed 6: 335 RPM", align="<"))
        layout.add_widget(Divider())
        layout.add_widget(Button("Quit", self._quit))
        self.fix()

    def _calculate(self):
        try:
            desired_temp = float(self.desired_temp.value)
            outdoor_temp = float(self.outdoor_temp.value)
            outdoor_humidity = float(self.outdoor_humidity.value)
            heart_rate = float(self.heart_rate.value)
            clothing_type = self.clothing_type.value

            # Input bounds validation
            if desired_temp < 16 or desired_temp > 32:
                self.result_box.value = "Error: Desired temperature must be between 16 and 32°C."
            elif outdoor_temp < desired_temp:
                self.result_box.value = "Error: Heating feature is not supported."
            elif outdoor_humidity > 75:
                self.result_box.value = ("Warning: It is better to directly set the AC to the desired temperature "
                                         "instead of using Efficient AI cooling with Fan Velocity.")
            else:
                # Convert heart rate to metabolic rate
                met = heart_rate_to_met(heart_rate)
                # Get clothing insulation value
                clo = clothing_insulation_mapping(clothing_type)
                
                velocity, ac_temp, final_pmv, lookup_table = find_air_velocity_and_ac_temp(desired_temp, outdoor_temp, outdoor_humidity, met, clo)

                # Find the appropriate fan RPM setting to achieve the calculated air velocity
                if velocity is None:
                    self.result_box.value = "Error: Unable to determine air velocity."
                else:
                    selected_rpm, selected_speed = map_air_velocity_to_rpm(velocity)

                    if selected_rpm is None:
                        self.result_box.value = "Error: Unable to achieve the desired air velocity with available fan RPM settings."
                    else:
                        self.result_box.value = (
                            f"To achieve a feel-like temperature of {desired_temp:.1f}°C:\n"
                            f"- Set the AC temperature to {ac_temp:.1f}°C\n"
                            f"- Set the fan speed to Speed {selected_speed} ({selected_rpm} RPM)\n"
                            f"Desired Air Velocity: {velocity:.2f} m/s\n"
                            f"Final PMV with AC and Fan combination: {final_pmv:.2f}\n"
                            f"Metabolic rate (met): {met:.2f}\n"
                            f"Clothing insulation (clo): {clo:.2f}"
                        )
        except ValueError:
            self.result_box.value = "Invalid input. Please enter numeric values."
        self.result_box.update(None)

    def _quit(self):
        from asciimatics.exceptions import StopApplication
        raise StopApplication("User requested exit.")

def demo(screen, scene):
    screen.play([Scene([ComfortApp(screen)], -1)], stop_on_resize=True, start_scene=scene)

def main():
    last_scene = None
    while True:
        try:
            Screen.wrapper(demo, catch_interrupt=True, arguments=[last_scene])
            sys.exit(0)
        except ResizeScreenError as e:
            last_scene = e.scene

if __name__ == "__main__":
    main()
