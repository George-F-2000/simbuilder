%% build_george_ems.m — construct GeorgeEMS_Knee.slx programmatically.
% The knee personality (PPO w_c=1 seed C) as a real Simulink model George can
% open, inspect, and edit: stock-FMU input names, the trained MLP wired from
% Gain/Bias/Tanh blocks (no black-box toolboxes), slew-limited split, torque
% envelopes, SOC integrator. Saves a diagram PNG, then attempts standalone
% FMU export (FMI 2.0 CS). v1 = traction knee core; regen path + full 19-pin
% mirror = v2 (Bible 28.11 / 27.4).
here = fileparts(mfilename('fullpath'));
pw = load(fullfile(here, 'knee_policy_weights.mat'));
fm = load(fullfile(here, 'stock_fmu_data', 'one_strlineacc_0_frnt_motor_data.mat'));
rm = load(fullfile(here, 'stock_fmu_data', 'one_strlineacc_0_rear_motor_data.mat'));

mdl = 'GeorgeEMS_Knee';
bdclose('all'); new_system(mdl);
set_param(mdl, 'SolverType', 'Fixed-step', 'Solver', 'FixedStepDiscrete', ...
          'FixedStep', '0.01');
mws = get_param(mdl, 'ModelWorkspace');
assignin(mws, 'W1', pw.W1); assignin(mws, 'b1', pw.b1);
assignin(mws, 'W2', pw.W2); assignin(mws, 'b2', pw.b2);
assignin(mws, 'W3', pw.W3); assignin(mws, 'b3', pw.b3);
assignin(mws, 'spd_f', double(fm.m_spd_data(:)')); assignin(mws, 'trq_f', double(fm.m_max_trq(:)'));
assignin(mws, 'spd_r', double(rm.m_spd_data(:)')); assignin(mws, 'trq_r', double(rm.m_max_trq(:)'));

ab = @(lib, name, varargin) add_block(lib, [mdl '/' name], 'MakeNameUnique','off', varargin{:});
% ---- inputs (stock FMU names) ----
ab('simulink/Sources/In1', 'throttle');
ab('simulink/Sources/In1', 'vehicle speed');
ab('simulink/Sources/In1', 'motor speed front');
ab('simulink/Sources/In1', 'motor speed rear');
% ---- demand: pedal^2 * available torque (traction_gamma=2, Ch.27.2) ----
ab('simulink/Math Operations/Gain', 'pedal frac', 'Gain', '0.01');
ab('simulink/Math Operations/Math Function', 'pedal sq', 'Operator', 'square');
ab('simulink/Lookup Tables/1-D Lookup Table', 'front envelope', ...
   'BreakpointsForDimension1', 'spd_f', 'Table', 'trq_f');
ab('simulink/Lookup Tables/1-D Lookup Table', 'rear envelope', ...
   'BreakpointsForDimension1', 'spd_r', 'Table', 'trq_r');
ab('simulink/Math Operations/Add', 'avail total', 'Inputs', '++');
ab('simulink/Math Operations/Product', 'T demand');
% ---- observation vector [v/55.55; T/591; SOC] ----
ab('simulink/Math Operations/Gain', 'norm v', 'Gain', '1/55.55');
ab('simulink/Math Operations/Gain', 'norm T', 'Gain', '1/591');
ab('simulink/Signal Routing/Mux', 'obs', 'Inputs', '3');
% ---- the trained MLP, in the open ----
ab('simulink/Math Operations/Gain', 'layer1 W', 'Gain', 'W1', 'Multiplication', 'Matrix(K*u)');
ab('simulink/Math Operations/Bias', 'layer1 b', 'Bias', 'b1');
ab('simulink/Math Operations/Trigonometric Function', 'tanh1', 'Operator', 'tanh');
ab('simulink/Math Operations/Gain', 'layer2 W', 'Gain', 'W2', 'Multiplication', 'Matrix(K*u)');
ab('simulink/Math Operations/Bias', 'layer2 b', 'Bias', 'b2');
ab('simulink/Math Operations/Trigonometric Function', 'tanh2', 'Operator', 'tanh');
ab('simulink/Math Operations/Gain', 'action W', 'Gain', 'W3', 'Multiplication', 'Matrix(K*u)');
ab('simulink/Math Operations/Bias', 'action b', 'Bias', 'b3');
ab('simulink/Discontinuities/Saturation', 'clip 0..1', 'UpperLimit','1', 'LowerLimit','0');
ab('simulink/Discontinuities/Rate Limiter', 'engage slew', ...
   'RisingSlewLimit', '2', 'FallingSlewLimit', '-2');
% ---- split + per-axle envelope clip ----
ab('simulink/Math Operations/Product', 'T rear raw');
ab('simulink/Sources/Constant', 'one', 'Value', '1');
ab('simulink/Math Operations/Add', 'one minus r', 'Inputs', '+-');
ab('simulink/Math Operations/Product', 'T front raw');
ab('simulink/Math Operations/MinMax', 'front clip', 'Function', 'min', 'Inputs', '2');
ab('simulink/Math Operations/MinMax', 'rear clip', 'Function', 'min', 'Inputs', '2');
% ---- SOC bucket (v1 approx: eta 0.85 total, stock 9472 Wh pack) ----
ab('simulink/Math Operations/Product', 'P front');
ab('simulink/Math Operations/Product', 'P rear');
ab('simulink/Math Operations/Add', 'P mech', 'Inputs', '++');
ab('simulink/Math Operations/Gain', 'to SOC rate', 'Gain', '-1/(0.85*9472*3600)');
ab('simulink/Discrete/Discrete-Time Integrator', 'SOC integ', ...
   'InitialCondition', '0.75', 'SampleTime', '0.01');
% ---- outputs (stock names, v1 subset) ----
ab('simulink/Sinks/Out1', 'front motor torque');
ab('simulink/Sinks/Out1', 'rear motor torque');
ab('simulink/Sinks/Out1', 'SOC');
ab('simulink/Sinks/Out1', 'torque ratio rear');

L = @(a, b) add_line(mdl, a, b, 'autorouting', 'on');
L('throttle/1', 'pedal frac/1');    L('pedal frac/1', 'pedal sq/1');
L('motor speed front/1', 'front envelope/1');
L('motor speed rear/1', 'rear envelope/1');
L('front envelope/1', 'avail total/1');  L('rear envelope/1', 'avail total/2');
L('pedal sq/1', 'T demand/1');      L('avail total/1', 'T demand/2');
L('vehicle speed/1', 'norm v/1');   L('T demand/1', 'norm T/1');
L('norm v/1', 'obs/1');  L('norm T/1', 'obs/2');  L('SOC integ/1', 'obs/3');
L('obs/1', 'layer1 W/1'); L('layer1 W/1', 'layer1 b/1'); L('layer1 b/1', 'tanh1/1');
L('tanh1/1', 'layer2 W/1'); L('layer2 W/1', 'layer2 b/1'); L('layer2 b/1', 'tanh2/1');
L('tanh2/1', 'action W/1'); L('action W/1', 'action b/1'); L('action b/1', 'clip 0..1/1');
L('clip 0..1/1', 'engage slew/1');
L('engage slew/1', 'T rear raw/1'); L('T demand/1', 'T rear raw/2');
L('one/1', 'one minus r/1');        L('engage slew/1', 'one minus r/2');
L('one minus r/1', 'T front raw/1'); L('T demand/1', 'T front raw/2');
L('T front raw/1', 'front clip/1'); L('front envelope/1', 'front clip/2');
L('T rear raw/1', 'rear clip/1');   L('rear envelope/1', 'rear clip/2');
L('front clip/1', 'P front/1');     L('motor speed front/1', 'P front/2');
L('rear clip/1', 'P rear/1');       L('motor speed rear/1', 'P rear/2');
L('P front/1', 'P mech/1');         L('P rear/1', 'P mech/2');
L('P mech/1', 'to SOC rate/1');     L('to SOC rate/1', 'SOC integ/1');
L('front clip/1', 'front motor torque/1');
L('rear clip/1', 'rear motor torque/1');
L('SOC integ/1', 'SOC/1');
L('engage slew/1', 'torque ratio rear/1');

Simulink.BlockDiagram.arrangeSystem(mdl);
save_system(mdl, fullfile(here, [mdl '.slx']));
print(['-s' mdl], '-dpng', '-r110', fullfile(here, 'GeorgeEMS_Knee_diagram.png'));
fprintf('SLX + diagram saved\n');
try
    exportToFMU2CS(mdl, 'SaveDirectory', here);
    fprintf('FMU EXPORTED OK\n');
catch e
    fprintf('FMU export deferred: %s\n', e.message);
end
