%% build_george_ems_v2.m — GeorgeEMS_Knee_v2: demand-parity edition.
% Same trained brain and 19-pin deck contract as v1.1, with the demand desk
% replaced by MEASUREMENT (Bible Ch.29 demand parity):
%   - 2-D lookup T_dem(pedal, vehicle speed) = the factory law, measured
%     point-by-point from the stock DLL (incl. coast band + regen region)
%   - 50 ms first-order demand filter (measured from stock pedal steps)
%   - negative-torque clipping so regen respects the envelopes
here = fileparts(mfilename('fullpath'));
pw = load(fullfile(here, 'knee_policy_weights.mat'));
fm = load(fullfile(here, 'stock_fmu_data', 'one_strlineacc_0_frnt_motor_data.mat'));
rm = load(fullfile(here, 'stock_fmu_data', 'one_strlineacc_0_rear_motor_data.mat'));
dl = load(fullfile(here, 'stock_demand_law.mat'));

mdl = 'GeorgeEMS_Knee_v2';
bdclose('all'); new_system(mdl);
set_param(mdl, 'SolverType', 'Fixed-step', 'Solver', 'FixedStepDiscrete', ...
          'FixedStep', '0.001');
mws = get_param(mdl, 'ModelWorkspace');
assignin(mws, 'W1', pw.W1); assignin(mws, 'b1', pw.b1);
assignin(mws, 'W2', pw.W2); assignin(mws, 'b2', pw.b2);
assignin(mws, 'W3', pw.W3); assignin(mws, 'b3', pw.b3);
assignin(mws, 'spd_f', double(fm.m_spd_data(:)')); assignin(mws, 'trq_f', double(fm.m_max_trq(:)'));
assignin(mws, 'spd_r', double(rm.m_spd_data(:)')); assignin(mws, 'trq_r', double(rm.m_max_trq(:)'));
assignin(mws, 'ped_bp', double(dl.ped_bp(:)')); assignin(mws, 'spd_bp', double(dl.spd_bp(:)'));
assignin(mws, 'Tmap', double(dl.Tmap));
assignin(mws, 'vcu_type', 4);

ab = @(lib, name, varargin) add_block(lib, [mdl '/' name], 'MakeNameUnique','off', varargin{:});
ab('simulink/Sources/In1', 'motorSpeedRear',  'Port', '1');
ab('simulink/Sources/In1', 'motorSpeedFront', 'Port', '2');
ab('simulink/Sources/In1', 'throttle',        'Port', '3');
ab('simulink/Sources/In1', 'vehicleSpeed',    'Port', '4');
% ---- demand desk v2: THE MEASURED FACTORY LAW ----
ab('simulink/Lookup Tables/2-D Lookup Table', 'measured demand map', ...
   'BreakpointsForDimension1', 'ped_bp', 'BreakpointsForDimension2', 'spd_bp', ...
   'Table', 'Tmap');
ab('simulink/Discrete/Discrete Transfer Fcn', 'demand filter 50ms', ...
   'Numerator', '[0.0198]', 'Denominator', '[1 -0.9802]', 'SampleTime', '0.001');
ab('simulink/Lookup Tables/1-D Lookup Table', 'creep lut', ...
   'BreakpointsForDimension1', '[0 0.5 1.0 1.5 2.0 3.0]', ...
   'Table', '[12 10 5 -60 -250 -1000]');
ab('simulink/Logic and Bit Operations/Compare To Constant', 'creep gate', ...
   'relop', '<', 'const', '12');
ab('simulink/Signal Attributes/Data Type Conversion', 'creep gate dbl', ...
   'OutDataTypeStr', 'double');
ab('simulink/Sources/Constant', 'no floor', 'Value', '-1e5');
ab('simulink/Signal Routing/Switch', 'creep switch', 'Criteria', 'u2 > Threshold', ...
   'Threshold', '0.5');
ab('simulink/Math Operations/MinMax', 'creep floor', 'Function', 'max', 'Inputs', '2');
% envelopes (for clipping only now)
ab('simulink/Lookup Tables/1-D Lookup Table', 'front envelope', ...
   'BreakpointsForDimension1', 'spd_f', 'Table', 'trq_f');
ab('simulink/Lookup Tables/1-D Lookup Table', 'rear envelope', ...
   'BreakpointsForDimension1', 'spd_r', 'Table', 'trq_r');
ab('simulink/Math Operations/Gain', 'neg env f', 'Gain', '-1');
ab('simulink/Math Operations/Gain', 'neg env r', 'Gain', '-1');
% ---- eyes ----
ab('simulink/Math Operations/Gain', 'norm v', 'Gain', '1/55.55');
ab('simulink/Math Operations/Gain', 'norm T', 'Gain', '1/591');
ab('simulink/Signal Routing/Mux', 'obs', 'Inputs', '3');
% ---- brain (unchanged) ----
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
% delivery guarantee: if |demand| exceeds the front envelope, the rear MUST
% take the excess (the stock map's red zone, as a rule): r_min =
% sat((|T|-envF)/max(|T|,1)); r_final = max(brain's slewed r, r_min)
ab('simulink/Math Operations/Abs', 'abs T');
ab('simulink/Sources/Constant', 'one Nm', 'Value', '1');
ab('simulink/Math Operations/MinMax', 'abs guard', 'Function', 'max', 'Inputs', '2');
ab('simulink/Math Operations/Add', 'excess', 'Inputs', '+-');
ab('simulink/Math Operations/Divide', 'r min raw');
ab('simulink/Discontinuities/Saturation', 'r min', 'UpperLimit','1', 'LowerLimit','0');
ab('simulink/Math Operations/MinMax', 'r final', 'Function', 'max', 'Inputs', '2');
% ---- split + double-sided envelope clip ----
ab('simulink/Math Operations/Product', 'T rear raw');
ab('simulink/Sources/Constant', 'one', 'Value', '1');
ab('simulink/Math Operations/Add', 'one minus r', 'Inputs', '+-');
ab('simulink/Math Operations/Product', 'T front raw');
ab('simulink/Math Operations/MinMax', 'front clip', 'Function', 'min', 'Inputs', '2');
ab('simulink/Math Operations/MinMax', 'rear clip', 'Function', 'min', 'Inputs', '2');
ab('simulink/Math Operations/MinMax', 'front floor', 'Function', 'max', 'Inputs', '2');
ab('simulink/Math Operations/MinMax', 'rear floor', 'Function', 'max', 'Inputs', '2');
% ---- powers + SOC ----
ab('simulink/Math Operations/Product', 'P front');
ab('simulink/Math Operations/Product', 'P rear');
ab('simulink/Math Operations/Add', 'P mech', 'Inputs', '++');
ab('simulink/Math Operations/Gain', 'batt P', 'Gain', '1/0.85');
ab('simulink/Math Operations/Gain', 'to SOC rate', 'Gain', '-1/(9472*3600)');
ab('simulink/Discrete/Discrete-Time Integrator', 'SOC integ', ...
   'InitialCondition', '0.75', 'SampleTime', '0.001');
% ---- flags + stubs + vcu anchor ----
ab('simulink/Logic and Bit Operations/Compare To Constant', 'state r', 'relop', '>', 'const', '0.5');
ab('simulink/Logic and Bit Operations/Compare To Constant', 'state f', 'relop', '>', 'const', '0.5');
ab('simulink/Signal Attributes/Data Type Conversion', 'state r dbl', 'OutDataTypeStr','double');
ab('simulink/Signal Attributes/Data Type Conversion', 'state f dbl', 'OutDataTypeStr','double');
ab('simulink/Sources/Constant', 'zero pwm r', 'Value', '0');
ab('simulink/Sources/Constant', 'zero pwm f', 'Value', '0');
ab('simulink/Sources/Constant', 'zero eff r', 'Value', '0');
ab('simulink/Sources/Constant', 'zero eff f', 'Value', '0');
ab('simulink/Sources/Constant', 'vcu type', 'Value', 'vcu_type');
ab('simulink/Sinks/Terminator', 'vcu sink');
names = {'rearMotorTorque','motorSpeedRearOut','tcrStateR','pwmRear', ...
  'powerDemandRear','frontMotorTorque','motorSpeedFrontOut','tcrStateFr', ...
  'pwmFront','powerDemandFront','SOC','combBattPowerDemand', ...
  'combMotorTorqueDemand','rearMotorEff','frontMotorEff','torqueSplitRear', ...
  'predCombTorqueDemand','torqueRatioRear','torqueRatioFront'};
for k = 1:19
    ab('simulink/Sinks/Out1', names{k}, 'Port', num2str(k));
end

L = @(a, b) add_line(mdl, a, b, 'autorouting', 'on');
L('throttle/1', 'measured demand map/1');
L('vehicleSpeed/1', 'measured demand map/2');
L('vehicleSpeed/1', 'creep lut/1');
L('throttle/1', 'creep gate/1');   L('creep gate/1', 'creep gate dbl/1');
L('creep lut/1', 'creep switch/1'); L('creep gate dbl/1', 'creep switch/2');
L('no floor/1', 'creep switch/3');
L('measured demand map/1', 'creep floor/1');
L('creep switch/1', 'creep floor/2');
L('creep floor/1', 'demand filter 50ms/1');
L('motorSpeedFront/1', 'front envelope/1');
L('motorSpeedRear/1', 'rear envelope/1');
L('front envelope/1', 'neg env f/1');  L('rear envelope/1', 'neg env r/1');
L('vehicleSpeed/1', 'norm v/1');       L('demand filter 50ms/1', 'norm T/1');
L('norm v/1', 'obs/1');  L('norm T/1', 'obs/2');  L('SOC integ/1', 'obs/3');
L('obs/1', 'layer1 W/1'); L('layer1 W/1', 'layer1 b/1'); L('layer1 b/1', 'tanh1/1');
L('tanh1/1', 'layer2 W/1'); L('layer2 W/1', 'layer2 b/1'); L('layer2 b/1', 'tanh2/1');
L('tanh2/1', 'action W/1'); L('action W/1', 'action b/1'); L('action b/1', 'clip 0..1/1');
L('clip 0..1/1', 'engage slew/1');
L('demand filter 50ms/1', 'abs T/1');
L('abs T/1', 'abs guard/1');        L('one Nm/1', 'abs guard/2');
L('abs T/1', 'excess/1');           L('front envelope/1', 'excess/2');
L('excess/1', 'r min raw/1');       L('abs guard/1', 'r min raw/2');
L('r min raw/1', 'r min/1');
L('engage slew/1', 'r final/1');    L('r min/1', 'r final/2');
L('r final/1', 'T rear raw/1');     L('demand filter 50ms/1', 'T rear raw/2');
L('one/1', 'one minus r/1');        L('r final/1', 'one minus r/2');
L('one minus r/1', 'T front raw/1'); L('demand filter 50ms/1', 'T front raw/2');
L('T front raw/1', 'front clip/1'); L('front envelope/1', 'front clip/2');
L('front clip/1', 'front floor/1'); L('neg env f/1', 'front floor/2');
L('T rear raw/1', 'rear clip/1');   L('rear envelope/1', 'rear clip/2');
L('rear clip/1', 'rear floor/1');   L('neg env r/1', 'rear floor/2');
L('front floor/1', 'P front/1');    L('motorSpeedFront/1', 'P front/2');
L('rear floor/1', 'P rear/1');      L('motorSpeedRear/1', 'P rear/2');
L('P front/1', 'P mech/1');         L('P rear/1', 'P mech/2');
L('P mech/1', 'batt P/1');          L('batt P/1', 'to SOC rate/1');
L('to SOC rate/1', 'SOC integ/1');
L('rear floor/1', 'state r/1');     L('state r/1', 'state r dbl/1');
L('front floor/1', 'state f/1');    L('state f/1', 'state f dbl/1');
L('vcu type/1', 'vcu sink/1');
L('rear floor/1', 'rearMotorTorque/1');
L('motorSpeedRear/1', 'motorSpeedRearOut/1');
L('state r dbl/1', 'tcrStateR/1');
L('zero pwm r/1', 'pwmRear/1');
L('P rear/1', 'powerDemandRear/1');
L('front floor/1', 'frontMotorTorque/1');
L('motorSpeedFront/1', 'motorSpeedFrontOut/1');
L('state f dbl/1', 'tcrStateFr/1');
L('zero pwm f/1', 'pwmFront/1');
L('P front/1', 'powerDemandFront/1');
L('SOC integ/1', 'SOC/1');
L('batt P/1', 'combBattPowerDemand/1');
L('demand filter 50ms/1', 'combMotorTorqueDemand/1');
L('zero eff r/1', 'rearMotorEff/1');
L('zero eff f/1', 'frontMotorEff/1');
L('r final/1', 'torqueSplitRear/1');
L('demand filter 50ms/1', 'predCombTorqueDemand/1');
L('r final/1', 'torqueRatioRear/1');
L('one minus r/1', 'torqueRatioFront/1');

Simulink.BlockDiagram.arrangeSystem(mdl);
save_system(mdl, fullfile(here, [mdl '.slx']));
fprintf('SLX saved\n');
wd = fullfile(getenv('TEMP'), 'george_fmu_build');
cd(wd);
exportToFMU2CS(mdl, 'SaveDirectory', wd);
copyfile(fullfile(wd, [mdl '.fmu']), fullfile(here, [mdl '.fmu']));
fprintf('FMU EXPORTED OK: %s\n', fullfile(here, [mdl '.fmu']));
