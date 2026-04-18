#version 330 core

in vec2  in_pos;
in float in_size;
in vec3  in_color;

uniform mat4 proj;

out vec3 v_color;

void main() {
    gl_Position  = proj * vec4(in_pos, 0.0, 1.0);
    gl_PointSize = in_size;
    v_color      = in_color;
}
