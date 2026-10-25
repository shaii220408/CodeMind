import {describe,expect,it,vi} from 'vitest';
import {resetAuthForm} from './authState.js';

describe('resetAuthForm',()=>{
  it('returns logout to a clean sign-in form',()=>{
    const setAuthMode=vi.fn(),setEmail=vi.fn(),setPassword=vi.fn();
    resetAuthForm({setAuthMode,setEmail,setPassword});
    expect(setAuthMode).toHaveBeenCalledWith('login');
    expect(setEmail).toHaveBeenCalledWith('');
    expect(setPassword).toHaveBeenCalledWith('');
  });
});
