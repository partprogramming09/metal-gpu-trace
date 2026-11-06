extends Node3D
## Builds a lit 3D scene from code: `meshes` spheres and boxes, `lights` omni lights (the first four cast shadows) and a sun.
## User arguments after `--`: meshes=N lights=N.

var meshes := 400
var lights := 8
var elapsed := 0.0
var camera: Camera3D


func _ready() -> void:
	for arg in OS.get_cmdline_user_args():
		var pair := arg.split("=")
		if pair.size() == 2 and pair[0] == "meshes":
			meshes = int(pair[1])
		elif pair.size() == 2 and pair[0] == "lights":
			lights = int(pair[1])
	camera = Camera3D.new()
	add_child(camera)
	var ground := MeshInstance3D.new()
	var plane := PlaneMesh.new()
	plane.size = Vector2(80, 80)
	ground.mesh = plane
	add_child(ground)
	var rng := RandomNumberGenerator.new()
	rng.seed = 1
	var material := StandardMaterial3D.new()
	material.albedo_color = Color(0.8, 0.5, 0.3)
	material.roughness = 0.4
	var sphere := SphereMesh.new()
	var box := BoxMesh.new()
	for i in meshes:
		var instance := MeshInstance3D.new()
		instance.mesh = sphere if i % 2 == 0 else box
		instance.material_override = material
		instance.position = Vector3(rng.randf_range(-30, 30), rng.randf_range(0.5, 6), rng.randf_range(-30, 30))
		add_child(instance)
	for i in lights:
		var light := OmniLight3D.new()
		light.omni_range = 18.0
		light.shadow_enabled = i < 4
		light.light_color = Color.from_hsv(rng.randf(), 0.5, 1.0)
		light.position = Vector3(rng.randf_range(-25, 25), 6, rng.randf_range(-25, 25))
		add_child(light)
	var sun := DirectionalLight3D.new()
	sun.shadow_enabled = true
	sun.rotation_degrees = Vector3(-50, 30, 0)
	add_child(sun)


func _process(delta: float) -> void:
	elapsed += delta
	camera.position = Vector3(sin(elapsed * 0.3) * 25.0, 12.0, cos(elapsed * 0.3) * 25.0)
	camera.look_at(Vector3.ZERO)
